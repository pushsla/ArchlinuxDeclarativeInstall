#!/usr/bin/python
import json
import sys
import getopt
import subprocess
import time

# What to do to setup some bootloaders correctly
_known_bootloaders = {
    'refind': {
        'setup': [('refind-install', [])]  # [setup1, setup2,,,] setup: (command, [*args])
    }
}

# How to deal with some initram generators and where to find files
_known_initrams = {
    'booster': {
        'img': lambda kern: '/boot/booster-' + kern + '.img',  # where to find image file
        'kern': lambda kern: '/boot/vmlinuz-' + kern,  # where to find kernel file
        'setup': [],  # [(setup_name, [arg1, arg2...]), (setup_name, [a1, a2...])]
        'uki_setup': []  # [(setup_name, [arg1, arg2...]), (setup_name, [a1, a2...])]
    },
    'mkinitcpio': {
        'img': lambda kern: '/boot/initramfs-' + kern + '.img',
        'kern': lambda kern: '/boot/vmlinuz' + kern,
        'setup': [],
        'uki_setup': []
    }
}

# Where to find needed files
_known_ucodes = {
    'intel-ucode': '/boot/intel-ucode.img',
    'amd-ucode': '/boot/amd-ucode.img',
}

# Information about current installation/configuration process
# What to do, what have been done, what are we ready/not for
_process = {
    'logfile': 'adi.log',
    'log_depth': 0,  # for pretty output look
    'satisfied': True,  # setup chain integrity
    'first_setup': 'configure_filesystems',  # chain starts from this step (can be modified by exec cmdline)
    'pacman_refreshed': False,
    'pkgbuild_ready': False,
    'setup_chain': [  # setup steps chain
        'configure_filesystems',
        'install_world',
        'install_kernel',
        'install_aur',
        'configure_userspace',
        'configure_world',
        'configure_boot',
        'save_configuration',
        'scripts',
        'script_packages',
    ],
    'needed_system_scripts': [],  # scripts that setup steps asked to install
    'needed_script_packages': [],  # packages needed for scripts ^
}

# Static installation/configuration data
# Where to install, what has been really installed and how program have been run
_options = {
    'install': "/mntarch",  # installation mount
    'root_uuid': "",  # UUID of root partition fixme is not used yet
    'installed_system_scripts': [],  # scripts actually installed in system
    'installed_script_packages': [],  # packages, needed by installed scripts and installed in system
    'params': [],  # cmdline params
    'arguments': [],  # params ^ values
    'configFile': "worldconfig.json", # path to install config
    'configData': {}  # deserialized content of install config
}

# Shortcuts for frequently used parts of _options
_system = _options['configData']['system']
_bootloader = _system['bootloader']


# Write log to file
def log(line) -> None:
    with open(_process['logfile'], 'a') as log:
        log.write('  ' * _process['log_depth'] + line + "\n")


# Pretty version of print() that automatically writes to log
def echo(*args, **kwargs) -> None:
    log('  ' * _process['log_depth'] + ' '.join(args))
    print('  ' * _process['log_depth'], *args, **kwargs)


# Pretty version of input() that writes prompt and answer to input
def read(prompt: str) -> str:
    answer = input('  ' * _process['log_depth'] + prompt)
    log(prompt + " " + answer)
    return answer


def run_command(cmd: str, args: list, user=None, nofail=False, direct=False, stdin: str = None, timeout=600,
                attempts=1) -> int:
    """
    Every command running in OS must be runned through this function.

    But if you want to chroot or change execution dir, dont use this function. See run_chroot() and run_chdir().

    :param cmd: command execution name
    :param args: arguments and further commands with their arguments
    :param user: run command by specified users name
    :param nofail: do not raise error on command execution fail (returncode != 0 ot timeout)
    :param direct: input/output will be transparent provided to current terminal
    :param stdin: sting that will be putted to process stdin (ignored if direct=True)
    :param timeout: process timeout before force kill
    :param attempts: if process fails (returncode != 0 or timeout) it can be restarted N-1 times
    :return: returncode of process. If, for some reason, process gives no returncode, will return 0
    """
    # For pretty log, echo, read look
    _process['log_depth'] += 1
    args = list(filter(lambda x: x != "", args))
    total_attempts = attempts

    # Use sudo to run from other user
    if user:
        command = "sudo --user=" + user + " " + ' '.join([cmd] + args)
    else:
        command = ' '.join([cmd] + args)

    echo('EXEC: ', command)

    # If there is stdin string, will create PIPE
    stdin_pipe = None
    if stdin:
        stdin_pipe = subprocess.PIPE

    # Because attempts. Guaranteed that will not be infinity by 'if' statements
    while True:
        # for process Timeout exception handling
        try:
            # Because for direct=True we do not write a log
            # fixme get rid of this IF
            if not direct:
                with open(_process['logfile'], 'a') as log:
                    log.write("<CommandOutput>\n")
                    p = subprocess.Popen(command, shell=True, stdin=stdin_pipe, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, encoding='utf-8')
                    output, err = p.communicate(input=stdin, timeout=timeout)
                    log.write(output)
                    log.write("\n<Error>\n" + err + "</Error>\n")
                    if err:
                        print(err)
                    log.write("\n</CommandOutput>\n")
            else:
                p = subprocess.Popen(command, shell=True, stdin=stdin_pipe, encoding='utf-8')
                p.communicate(input=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()

        # If no returncode, set it as 0
        result = p.returncode if p.returncode else 0
        echo("  RET: {}".format(result))

        # Cycle end guarantee
        if result == 0:
            break
        elif attempts > 1:
            echo("Failed {}/{} attempts. Retrying...".format(attempts, total_attempts))
            attempts -= 1
        elif nofail:
            break
        else:
            raise Exception('  ' * _process['log_depth'] + "Command Error!")
    _process['log_depth'] -= 1
    return result


def run_chroot(cmd: str, args: list, user=None, **kwargs) -> int:
    """
    Run command in installation chroot.

    If you need to run command in chroot, dont use run_command. Use this function.
    But if you need to execute in some directory, dont use run_chroot. Look for run_chdir(chroot=True).

    :param cmd: command execution name
    :param args: arguments and further commands with their arguments
    :param user: run command by specified users name
    :param kwargs: other keywork arguments for run_command
    :return: full execution returncode
    """
    # We have to deal with user there, not in run_command
    # Because if we use run_command, cmd looks like 'sudo arch-chroot'.
    # Not a thing we want. We need arch-chroot /mnt sudo:
    if user:
        return run_command("arch-chroot", [_options['install'], 'sudo', '--user=' + user, cmd] + args, **kwargs)
    return run_command("arch-chroot", [_options['install'], cmd] + args, **kwargs)


def run_chdir(path: str, cmd: str, args: list, chroot=False, user=None, **kwargs) -> int:
    """
    Run command in special directory.

    If you need to run command in some directory locally, dont use run_command. Use this function.
    Also, dont use run_chroot if you want to chroot and run command in some directory.

    :param path: local directory path
    :param cmd: command execution name
    :param args: arguments and further commands with their arguments
    :param chroot: do a chroot to installation, then cd, then cmd
    :param user: run command by specified users name
    :param kwargs: arguments for run_command and run_chroot (if chroot=True)
    :return: full execution returncode
    """
    # We have to deal with chroot here, not in run_chroot
    # Because if we use run_chroot directly, command will be arch-chroot /mnt cd ...
    # We need arch-chroot /mnt sh -c "cd... because only this will work
    if chroot:
        return run_chroot("sh", ['-c', '"', 'cd', path, '&&', cmd] + args + ['"'], user=user, **kwargs)
    # For the same ^ reasons we dealing with user here
    if user:
        return run_command("sudo", ['--user=' + user, 'sh', '-c', '"', 'cd', path, '&&', cmd, *args, '"'], **kwargs)
    return run_command("cd", [path, '&&', cmd] + args, user=user, **kwargs)


def run_setup(function: run_command, *args, required=True, **kwargs) -> None:
    """
    Run setup function by its reference and give parameters to it.

    Use this function only for chain setups running. This function is looking for
    chain integrity and will not allow to continue installation/configuration if any
    important setup step fails.

    Running function must return True for sucessfull running and False/None for unsucessful.

    :param function: function that returns True/False
    :param args: arguments passed to function
    :param required: is this setup step required for whole installation/setup process
    :param kwargs: arguments passed to function
    """
    _process['log_depth'] += 1
    echo("Step: ", function.__name__)
    # Run every step only if chain integrity is present
    if _process['satisfied']:
        # any error unhandled inside running function interpreted as fail
        try:
            result = function(*args, **kwargs)
        except Exception as err:
            echo(str(err))
            result = False

        if not result and required:
            # Chain integrity failed
            _process['satisfied'] = False

        echo("OK" if result else "Err!")
    else:
        echo('Unsatisfied! Abort')
    _process['log_depth'] -= 1


def install_pacstrap(packages: list) -> bool:
    """
    Install package to installation with pacstrap.

    Use this function to install core/extra/community packages only. Instead of manual calling.

    :param packages: list of installing packages
    :return: True if installation was sucessfull
    """
    # Check if pacman db was not synced and sync if needed
    if not _process['pacman_refreshed']:
        run_command('pacman', ['-Sy'])
        # Sync once for installation
        _process['pacman_refreshed'] = True

    run_command('pacstrap', [_options['install']] + packages)
    return True


def remove_packages(packages: list) -> bool:
    """
    Remove packages from installation.

    Use this function to remove any packages from installation instead of manual calling

    :param packages: package list to remove
    :return: True in ANY case! Even if some dependencies were not satisfied!
    """
    # Remove packages one by one.
    for pkg in packages:
        # If removal fails, continue. There are many packages to remove.
        run_chroot('pacman', ['-Rsn', '--noconfirm', pkg], nofail=True)
    return True


def install_local_pacman(packages: list) -> bool:
    """
    Install packages locally in current running OS.

    Use this function to install core/extra/community packages only. Instead of manual calling.

    :param packages: package list to install
    :return: True if installation succeed
    """
    if not _process['pacman_refreshed']:
        run_command('pacman', ['-Sy'])
        _process['pacman_refreshed'] = True

    run_command('pacman', ['-S', '--noconfirm'] + packages)
    return True


def remove_local_packages(packages: list) -> bool:
    """
    Remove packages from local current running OS.

    Use this function to remove any packages from current OS instead of manual calling

    :param packages: package list to remove
    :return: True in ANY case.
    """
    for pkg in packages:
        # If removal fails, continue. There are many packages to remove.
        run_command('pacman', ['-Rsn', '--noconfirm', pkg], nofail=True)
    return True


def install_pkgbuild(pkg: str, dependencies: list) -> bool:
    """
    MUST SPECIFY DEPENDENCIES MANUALLY.

    Install ONE package and its dependencies from AUR to installation.
    This function WILL NOT CHECK dependencies.
    It executes MAKEPKG with "-d" flag.

    :param pkg: package name
    :param dependencies: ALL UNINSTALLED package make- and run- dependencies
    :return: True in ANY case.
    """
    # Git is needed to clone PKGBUILD
    if not _process['pkgbuild_ready']:
        install_local_pacman(['git'])
        _process['pkgbuild_ready'] = True

    # Building is performed in installation fs
    dir = "/usr/local/tmp/adi/makepkg/"
    src_f = lambda name: "https://aur.archlinux.org/" + name + ".git"

    install_pacstrap(dependencies)

    run_command('mkdir', ['-p', dir])
    run_command('git', ['clone', src_f(pkg), dir + pkg])
    run_command('chmod', ['-R', '777', dir + pkg])
    # if makepkg -d runs without fails we will pacman -U
    if run_chdir(dir + pkg, 'makepkg', ['-d'], user="nobody", nofail=True, chroot=True) == 0:
        run_chroot('pacman', ['-U', dir + pkg + "/*.pkg.*"])
    else:
        echo("Package was not installed due MAKEPKG FAIL")

    return True


def parse_options(argv: list) -> bool:
    """
    Parse program execution parameters from cmdline

    :param argv: list of parameters+values
    :return: True if all fine
    """
    try:
        _options['params'], _options['arguments'] = getopt.getopt(argv, "c:i:s:",
                                                                  ['config=', 'install=', 'setup=', 'scripts='])
    except getopt.GetoptError:
        echo("Invalid option")

    for opt, arg in _options['params']:
        arg = arg if arg[0] not in (' ') else arg[1:]
        if opt in ('-c', '--config'):
            _options['configFile'] = arg
        elif opt in ('-i', '--install'):
            _options['install'] = arg
        elif opt in ('-s', '--setup'):
            _process['first_setup'] = arg
        elif opt in ('--scripts'):
            _process['needed_system_scripts'] = arg.split(',')

    return True


def read_config() -> bool:
    """
    Read configuraton file.

    File name stored in _options and can be changed with cmline option.
    :return: True if all fine
    """
    with open(_options['configFile'], 'r') as file:
        _options['configData'] = json.load(file)

    return True


def save_config(path: str = None) -> bool:
    """
    Save installation/configuration data.

    :param path: path to save.
    :return: True if all fine
    """
    path = path if path else _options['configFile']
    with open(path, 'w') as file:
        json.dump(_options['configData'], file)

    return True


def save_run(path: str) -> bool:
    """
    Save whole _options file.

    Needed for some post-installation workers.

    :param path: path to save
    :return: True if all fine
    """
    with open(path, 'w') as file:
        json.dump(_options, file)

    return True


def configure_filesystems() -> bool:
    """
    Creates filesystems, mounts them as stated in config.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True is all fine
    """
    swaps = []  # Swap partitions
    mounts = []
    rootmount = {}  # Root filesystem device config
    partitions = _options['configData']['hardware']['partitions']

    for part in partitions:
        if part['dev']:
            run_command('umount', ['-f', part['dev']], nofail=True)

        if part['mount']:
            if part['mount'] == '/':
                rootmount = part
            else:
                mounts.append(part)

    # Rootmount must be
    if not rootmount:
        raise Exception("No Root mountpoint was specified in config!")

    # Root partition can be mounted because it was not unmounted earlier for "busy" error.
    run_command('umount', ['-f', rootmount['dev']], nofail=True)

    for part in partitions:
        if part['dev']:
            if part['fs'] == 'swap':
                swaps.append(part)
                mkfs = "mkswap"
            # If fs is empty, we will not format device
            elif not part['fs']:
                continue
            else:
                mkfs = "mkfs." + part['fs']

            run_command(mkfs, [part['fs_options'], part['dev']])

    run_command('mkdir', [_options['install'], '-p'])
    run_command('mount', [rootmount['mount_options'], rootmount['dev'], _options['install'] + rootmount['mount']])

    for mount in mounts:
        run_command('mkdir', ['-p', _options['install'] + mount['mount']])
        run_command('mount', [mount['mount_options'], mount['dev'], _options['install'] + mount['mount']])

    for swap in swaps:
        run_command('swapon', [swap['dev']])

    return True


def install_world() -> bool:
    """
    Install all system packages.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True is all fine
    """
    install_pacstrap(_options['configData']['packages'])

    if _bootloader['install_bootloader']:
        install_pacstrap([_bootloader['used_bootloader']])
    return True


def install_kernel() -> bool:
    """
    Install all needed kernels.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    install_pacstrap([
                         _system['initram'],
                         _system['ucode']
                     ] + [k['version'] for k in _system['kernels']]
                     )
    return True


def install_aur() -> bool:
    """
    Install packages from AUR, specefied in installation config.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    packages = _options['configData']['aur_packages']
    for pkg in packages:
        pkgname = pkg['name']
        pkgdeps = pkg['deps']
        pkgmake = pkg['make_deps']
        rm_make = pkg['remove_make_deps']

        install_pkgbuild(pkgname, pkgdeps+pkgmake)
        # if stated, remove make-dependencies after installation
        if rm_make:
            remove_packages(pkgmake)

    return True


def configure_world() -> bool:
    """
    System-wide configurations not related to userspace.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    run_chroot('timedatectl', ['set-timezone', _system['systemd']['timezone']])
    run_chroot('timedatectl', ['set-ntp', _system['systemd']['ntp']])
    run_chroot('hostnamectl', ['set-hostname', _system['systemd']['hostname']])

    run_command('echo', ['-e', '\"{}\"'.format('\\n'.join(_system['systemd']['locales'])), '>',
                         _options['install'] + "/etc/locale.gen"])
    run_chroot('locale-gen', [])
    run_chroot('localectl', ['set-locale', "LANG=" + _system['systemd']['main_locale']], nofail=True)

    run_command('genfstab', ["-U", _options['install'], '>>', _options['install'] + "/etc/fstab"])

    echo("Configure ROOT password (safe UNIX passwd command used. Enter password Twice!):")
    run_chroot('passwd', ['root'], direct=True, attempts=2)

    return True


def configure_userspace() -> bool:
    """
    Configurations related to userspace and UX.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    users = _system['users']
    for user in users:
        home = ["-m"] if user['home'] else []
        groups = ["-G", ','.join(user['groups'])] if user['groups'] else []
        shell = ["-s", user['shell']] if user['shell'] else []

        run_chroot('useradd', home + groups + shell + [user['name']], nofail=True)
        if user['password']:
            echo("Configure {}`s password (safe UNIX passwd command used. Enter password Twice!):".format(user['name']))
            run_chroot('passwd', [user['name']], direct=True, attempts=2)

    install_pacstrap([_system['desktop'], _system['dm']])
    run_chroot('systemctl', ['enable', _system['dm']])

    if _options['configData']['features']['hfp_ofono']:
        _process['needed_system_scripts'].append(script_hfp_ofono.__name__)

    return True


def configure_boot() -> bool:
    """
    Configure system boot process if possible.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    echo("Currenlty supported image generators are: " + str(list(_known_initrams.keys())))
    echo("Currenlty supported bootloaders are: " + str(list(_known_bootloaders.keys())))

    if _bootloader['install_bootloader']:
        if (blname := _bootloader['used_bootloader']) in _known_bootloaders.keys():
            for cmd, args in _known_bootloaders[blname]['setup']:
                run_chroot(cmd, args)
        else:
            echo("I have no idea what to do with this bootloader! You have to configure it manually!")

    if (ininame := _system['initram']) in _known_initrams.keys():
        for step, args in _known_initrams[ininame]['setup']:
            run_setup(step, *args)

    # Unified Kernel Image
    if _bootloader['uki']['use_uki']:
        run_setup(uki_efistub)

    return True


def uki_efistub() -> bool:
    """
    Create and, possibly, add script to generate Unified Kernel Image.

    Installation chain step.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    if (ininame := _system['initram']) in _known_initrams.keys():
        for step, args in _known_initrams[ininame]['uki_setup']:
            run_setup(step, *args)

        for kern_data in _system['kernels']:
            kernel = kern_data['version']
            kernelpath = _known_initrams[ininame]['kern'](kernel)
            cmdline = kern_data['cmdline']
            initram = _known_initrams[ininame]['img'](kernel)
            ucode = _known_ucodes[_system['ucode']] if _system['ucode'] in _known_ucodes.keys() else None

            run_command('mkdir', ['-p', _options['install'] + _bootloader['uki']['gen_dest']])
            run_command('echo', ['\"{}\"'.format(cmdline), '>', _options['install'] + '/etc/kernel/cmdline-' + kernel])

            if ucode:
                run_command('cat',
                            [ucode, initram, '>', ''.join(initram.split('.')[:-1]) + "-" + _system['ucode'] + '.img'])
                initram_ucode = ''.join(initram.split('.')[:-1]) + "-" + _system['ucode'] + '.img'
                ukipath = _options['install'] + _bootloader['uki']['gen_dest'] + "/" + kernel + ".efi"

            uki_params = [
                '--add-section .osrel="{}/usr/lib/os-release" --change-section-vma .osrel=0x20000'.format(
                    _options['install']),
                '--add-section .cmdline="{}/etc/kernel/cmdline-{}" --change-section-vma .cmdline=0x30000'.format(
                    _options['install'], kernel),
                '--add-section .linux="{}" --change-section-vma .linux=0x2000000'.format(kernelpath),
                '--add-section .initrd="{}" --change-section-vma .initrd=0x3000000'.format(initram_ucode),
                '"/usr/lib/systemd/boot/efi/linuxx64.efi.stub" "{}"'.format(ukipath)
            ]

            run_command('rm', [ukipath], nofail=True)
            run_command('objcopy', uki_params)

        if _bootloader['uki']['add_hook']:
            _process['needed_system_scripts'].append(script_booster_uki.__name__)
    else:
        echo("I Have ho idea what to do with {} initram generator!".format(ininame))

    return True


def save_configuration() -> bool:
    """
    Save configurations to local OS and to installation.

    Installation chain step.
    Have to be used in run_step() only.

    Configuration in installation needed for some scripts, that will work under installation OS later.

    :return: True if all fine
    """
    echo("Configuraton and system-descripting files are stored in /usr/local/share/adi")
    run_command('mkdir', ['-p', '/usr/local/share/adi/'])
    run_command('mkdir', ['-p', _options['install'] + '/usr/local/share/adi/'])
    run_setup(save_run, '/usr/local/share/adi/your_system.json')
    run_setup(save_config, '/usr/local/share/adi/your_config.json')
    run_setup(save_run, _options['install'] + '/usr/local/share/adi/your_system.json')
    run_setup(save_config, _options['install'] + '/usr/local/share/adi/your_config.json')

    return True


def scripts() -> bool:
    """
    Run all scripts.

    Installation chain step.
    Have to be used in run_step() only.

    :return:
    """
    echo("Current scripts queue: " + str(_process['needed_system_scripts']))
    for script in set(_process['needed_system_scripts']):
        run_setup(eval(script))
        _options['installed_system_scripts'].append(script)
    return True


def script_booster_uki() -> bool:
    """
    Make installation OS to regenerate UKI images every time kernel is updated.

    Installation chain step. Script that affects target OS.
    Have to be used in run_step() only.

    :return: True if all fine
    """
    echo("UKI Generation script will be installed to /usr/local/share/adi/scripts")
    echo("UKI Generation Pacman Hook will be installed to /etc/pacman.d/hooks")
    _process['needed_script_packages'] += ['python', 'binutils', 'systemd']

    run_command('mkdir', ['-p', _options['install'] + "/usr/local/share/adi/scripts"])
    run_command('mkdir', ['-p', _options['install'] + "/etc/pacman.d/hooks"])
    run_command('cp', ['-f', 'hooks/99-adi-uki.hook', _options['install'] + "/etc/pacman.d/hooks/"])
    run_command('cp', ['-f', 'scripts/uki', _options['install'] + "/usr/local/share/adi/scripts/"])
    run_command('chmod', ['+x', _options['install'] + "/usr/local/share/adi/scripts/uki"])
    return True


def script_hfp_ofono() -> bool:
    echo("Sorry! Not implemented yet! I have troubles with PKGBUILDing.")
    return True


def script_packages() -> bool:
    """
    Install packages needed by scripts for their properly work.

    Installation chain step.
    Have to be used in run_step() only.

    :return:
    """
    echo("Additional packages will be installed: " + str(_process['needed_script_packages']))
    packages = list(set(_process['needed_script_packages']) - set(_options['configData']['packages']))
    install_pacstrap(packages)
    _options['installed_script_packages'] += packages
    return True


if __name__ == "__main__":
    run_setup(parse_options, sys.argv[1:])
    run_setup(read_config)

    # User is able to start process not from beginning for some reason
    try:
        setup_first_index = _process['setup_chain'].index(_process['first_setup'])
    except ValueError:
        echo("No such chain! Will start from first setup!")
        setup_first_index = 0

    echo("Current setup chain: " + str(_process['setup_chain'][setup_first_index:]))

    time.sleep(5)

    # run all steps
    for setup in _process['setup_chain'][setup_first_index:]:
        run_setup(eval(setup))
