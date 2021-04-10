#!/usr/bin/python
import json
import sys
import getopt
import subprocess
import time

supported_bootloaders = {
    'refind': {
        'install': [('refind-install', [])]  # [setup1, setup2,,,] setup: (command, [*args])
    }
}

supported_initrams = {
    'booster': {
        'img': lambda kern: '/boot/booster-'+kern+'.img',
        'kern': lambda kern: '/boot/vmlinuz-'+kern,
        'setup': [],  # [(setup_name, [arg1, arg2...]), (setup_name, [a1, a2...])]
        'uki_setup': []  # [(setup_name, [arg1, arg2...]), (setup_name, [a1, a2...])]
    },
    'mkinitcpio': {
        'img': lambda kern: '/boot/initramfs-'+kern+'.img',
        'kern': lambda kern: '/boot/vmlinuz'+kern,
        'setup': [],  # [(setup_name, [arg1, arg2...]), (setup_name, [a1, a2...])]
        'uki_setup': []  # [(setup_name, [arg1, arg2...]), (setup_name, [a1, a2...])]
    }
}

supported_ucodes = {
    'intel-ucode': '/boot/intel-ucode.img',
    'amd-ucode': '/boot/amd-ucode.img',
}

process = {
    'logfile': 'adi.log',
    'log_depth': 0,
    'satisfied': True,
    'first_setup': 'configure_filesystems',
    'pkgbuild_ready': False,
    'pacman_refreshed': False,
    'setup_chain': [
        'configure_filesystems',
        'install_world',
        'install_kernel',
        'configure_userspace',
        'configure_world',
        'configure_boot',
        'save_configuration',
        'scripts',
        'script_packages'
    ],
    'needed_system_scripts': [],
    'needed_script_packages': [],
}

options = {
    'install': "/mntarch",
    'root_uuid': "",
    'installed_system_scripts': [],
    'installed_script_packages': [],
    'params': [],
    'arguments': [],
    'configFile': "worldconfig.json",
    'configData': {}
}


def log(line) -> None:
    with open(process['logfile'], 'a') as log:
        log.write('  ' * process['log_depth']+line+"\n")


def echo(*args, **kwargs) -> None:
    log('  ' * process['log_depth']+' '.join(args))
    print('  ' * process['log_depth'], *args, **kwargs)


def read(prompt: str) -> str:
    answer = input('  ' * process['log_depth']+prompt)
    log(prompt+" "+answer)
    return answer


def run_command(cmd: str, args: list, nofail=False, direct=False, attempts=1) -> int:
    process['log_depth'] += 1
    args = list(filter(lambda x: x != "", args))
    echo('EXEC: ', cmd + ' ' + ' '.join(args))
    process['log_depth'] -= 1
    return 0

    total_attempts = attempts
    while True:
        if not direct:
            with open(process['logfile'], 'a') as log:
                log.write("<CommandOutput>\n")
                p = subprocess.Popen(' '.join([cmd] + args), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                result = p.wait()
                output, err = p.communicate()
                log.write(output.decode('utf-8'))
                log.write("\n<Error>\n"+err.decode('utf-8')+"</Error>\n")
                if err:
                    print(err.decode('utf-8'))
                log.write("\n</CommandOutput>\n")
        else:
            result = subprocess.Popen(' '.join([cmd] + args), shell=True).wait()
        if result == 0:
            break
        elif attempts > 1:
            echo("Failed {}/{} attempts. Retrying...".format(attempts, total_attempts))
            attempts -= 1
        elif not nofail:
            break
        else:
            raise Exception('  ' * process['log_depth'] + "Command Error!")
    process['log_depth'] -= 1
    return result


def run_chroot(cmd: str, args: list, nofail=False, direct=False, attempts=1) -> (int, str):
    run_command("arch-chroot", [options['install'], cmd] + args, nofail=nofail, direct=direct, attempts=attempts)


def run_setup(function: run_command, *args, required=True, **kwargs):
    process['log_depth'] += 1
    echo("Step: ", function.__name__)
    if process['satisfied']:
        try:
            result = function(*args, **kwargs)
        except Exception as err:
            echo(str(err))
            result = False

        if not result and required:
            process['satisfied'] = False

        echo("OK" if result else "Err!")
    else:
        echo('Unsatisfied! Abort')
    process['log_depth'] -= 1


def install_pacstrap(packages: list) -> bool:
    if not process['pacman_refreshed']:
        run_command('pacman', ['-Sy'])
        process['pacman_refreshed'] = True

    run_command('pacstrap', [options['install']] + packages)
    return True


def install_local_pacman(packages: list) -> bool:
    if not process['pacman_refreshed']:
        run_command('pacman', ['-Sy'])
        process['pacman_refreshed'] = True

    run_command('pacman', ['-S', '--noconfirm']+packages)
    return True


def install_pkgbuild(package_name: str) -> bool:
    if not process['pkgbuild_ready']:
        install_local_pacman(['git'])
        process['pkgbuild_ready'] = True

    run_command('mkdir', ['-p', '/tmp/adi/build/'])
    run_command('mkdir', ['-p', options['install']+'/tmp/adi/build/'])
    run_command('git', ['clone', "https://aur.archlinux.org/{}.git".format(package_name), '/tmp/adi/build/'])
    run_command('sudo', ['-u', 'nobody', 'cd', '/tmp/adi/build/'+package_name, '&&', 'makepkg', '-s'])
    run_command('cp', ['/tmp/adi/build/'+package_name+"*.tar.*", options['install']+'/tmp/adi/build/'])
    echo("Now you have to run pacman -U <package_name> and then exit the shell")
    run_chroot('cd', ['/tmp/adi/build/'], direct=True)
    return True


def parse_options(argv: list) -> bool:
    try:
        options['params'], options['arguments'] = getopt.getopt(argv, "c:i:s:", ['config=', 'install=', 'setup=','scripts='])
    except getopt.GetoptError:
        echo("Invalid option")

    for opt, arg in options['params']:
        arg = arg if arg[0] not in (' ') else arg[1:]
        if opt in ('-c', '--config'):
            options['configFile'] = arg
        elif opt in ('-i', '--install'):
            options['install'] = arg
        elif opt in ('-s', '--setup'):
            process['first_setup'] = arg
        elif opt in ('--scripts'):
            process['needed_system_scripts'] = arg.split(',')

    return True


def read_config() -> bool:
    with open(options['configFile'], 'r') as file:
        options['configData'] = json.load(file)

    return True


def save_config(path: str = None) -> bool:
    path = path if path else options['configFile']
    with open(path, 'w') as file:
        json.dump(options['configData'], file)

    return True


def save_run(path: str) -> bool:
    with open(path, 'w') as file:
        json.dump(options, file)

    return True


def configure_filesystems() -> bool:
    swaps = []
    mounts = []
    rootmount = {}
    partitions = options['configData']['hardware']['partitions']

    for part in partitions:
        if part['dev']:
            run_command('umount', ['-f', part['dev']], nofail=True)

        if part['mount']:
            if part['mount'] == '/':
                rootmount = part
            else:
                mounts.append(part)

    run_command('umount', ['-f', rootmount['dev']], nofail=True)

    for part in partitions:
        if part['dev']:
            if part['fs'] == 'swap':
                swaps.append(part)
                mkfs = "mkswap"
            elif not part['fs']:
                continue
            else:
                mkfs = "mkfs." + part['fs']

            run_command(mkfs, [part['fs_options'], part['dev']])

    if not rootmount:
        raise Exception("No Root mountpoint was specified in config!")

    run_command('mkdir', [options['install'], '-p'])
    run_command('mount', [rootmount['mount_options'], rootmount['dev'], options['install'] + rootmount['mount']])

    for mount in mounts:
        run_command('mkdir', ['-p', options['install'] + mount['mount']])
        run_command('mount', [mount['mount_options'], mount['dev'], options['install'] + mount['mount']])

    for swap in swaps:
        run_command('swapon', [swap['dev']])

    return True


def install_world() -> bool:
    run_command('pacman', ['-Sy'])
    install_pacstrap(options['configData']['packages'])

    if options['configData']['system']['bootloader']['install_bootloader']:
        install_pacstrap([options['configData']['system']['bootloader']['used_bootloader']])
    return True


def install_kernel() -> bool:
    install_pacstrap([
        options['configData']['system']['initram'],
        options['configData']['system']['ucode']
    ]+[k['version'] for k in options['configData']['system']['kernels']]
    )
    return True


def configure_world() -> bool:
    system = options['configData']['system']
    run_chroot('timedatectl', ['set-timezone', system['systemd']['timezone']])
    run_chroot('timedatectl', ['set-ntp', system['systemd']['ntp']])
    run_chroot('hostnamectl', ['set-hostname', system['systemd']['hostname']])

    run_command('echo', ['-e', '\"{}\"'.format('\\n'.join(system['systemd']['locales'])), '>',
                         options['install'] + "/etc/locale.gen"])
    run_chroot('locale-gen', [])
    run_chroot('localectl', ['set-locale', "LANG=" + system['systemd']['main_locale']], nofail=True)
    run_command('genfstab', ["-U", options['install'], '>>', options['install'] + "/etc/fstab"])

    echo("Configure ROOT password (safe UNIX passwd command used. Enter password Twice!):")
    run_chroot('passwd', ['root'], direct=True, attempts=2)

    return True


def configure_userspace() -> bool:
    users = options['configData']['system']['users']
    for user in users:
        home = ["-m"] if user['home'] else []
        groups = ["-G", ','.join(user['groups'])] if user['groups'] else []
        shell = ["-s", user['shell']] if user['shell'] else []

        run_chroot('useradd', home + groups + shell + [user['name']], nofail=True)
        if user['password']:
            echo("Configure {}`s password (safe UNIX passwd command used. Enter password Twice!):".format(user['name']))
            run_chroot('passwd', [user['name']], direct=True, attempts=2)

    install_pacstrap([options['configData']['system']['desktop'], options['configData']['system']['dm']])
    run_chroot('systemctl', ['enable', options['configData']['system']['dm']])

    if options['configData']['features']['hfp_ofono']:
        process['needed_system_scripts'].append(script_hfp_ofono.__name__)

    return True


def configure_boot() -> bool:
    echo("Currenlty supported image generators are: booster")
    echo("Currenlty supported bootloaders are: refind")

    system = options['configData']['system']
    bootloader = system['bootloader']

    if bootloader['install_bootloader']:
        if blname := bootloader['used_bootloader'] in supported_bootloaders.keys():
            for cmd, args in supported_bootloaders[blname]:
                run_chroot(cmd, args)
        else:
            echo("I have no idea what to do with this bootloader! You have to configure it and EFISTUB manually!")

    if ininame := system['initram'] in supported_initrams.keys():
        for step, args in supported_initrams[ininame]['setup']:
            run_setup(step, *args)

    if system['uki']['use_uki']:
        run_setup(uki_efistub)

    return True


def uki_efistub() -> bool:
    system = options['configData']['system']
    bootloader = system['bootloader']

    if ininame := system['initram'] in supported_initrams.keys():
        for step, args in supported_initrams[ininame]['uki_setup']:
            run_setup(step, *args)

        for kern_data in system['kernels']:
            kernel = kern_data['version']
            kernelpath = supported_initrams[ininame]['kern'](kernel)
            cmdline = kern_data['cmdline']
            initram = supported_initrams[ininame]['img'](kernel)
            ucode = supported_ucodes[system['ucode']] if system['ucode'] in supported_ucodes.keys() else None

            run_command('mkdir', ['-p', options['install'] + bootloader['uki']['gen_dest']])
            run_command('echo', ['\"{}\"'.format(cmdline), '>', options['install'] + '/etc/kernel/cmdline-' + kernel])

            if ucode:
                run_command('cat', [ucode, initram, '>', ''.join(initram.split('.')[:-1]) + "-" + system['ucode'] + '.img'])
                initram_ucode = ''.join(initram.split('.')[:-1]) + "-" + system['ucode'] + '.img'
                ukipath = options['install'] + bootloader['uki']['gen_dest'] + "/" + kernel + ".efi"

            uki_params = [
                '--add-section .osrel="{}/usr/lib/os-release" --change-section-vma .osrel=0x20000'.format(
                    options['install']),
                '--add-section .cmdline="{}/etc/kernel/cmdline-{}" --change-section-vma .cmdline=0x30000'.format(
                    options['install'], kernel),
                '--add-section .linux="{}" --change-section-vma .linux=0x2000000'.format(kernelpath),
                '--add-section .initrd="{}" --change-section-vma .initrd=0x3000000'.format(initram_ucode),
                '"/usr/lib/systemd/boot/efi/linuxx64.efi.stub" "{}"'.format(ukipath)
            ]

            run_command('rm', [ukipath], nofail=True)
            run_command('objcopy', uki_params)

        if bootloader['uki']['add_hook']:
            process['needed_system_scripts'].append(script_booster_uki.__name__)
    else:
        echo("I Have ho idea what to do with {} initram generator!".format(ininame))

    return True


def save_configuration() -> bool:
    echo("Configuraton and system-descripting files are stored in /usr/local/share/adi")
    run_command('mkdir', ['-p', '/usr/local/share/adi/'])
    run_command('mkdir', ['-p', options['install'] + '/usr/local/share/adi/'])
    run_setup(save_run, '/usr/local/share/adi/your_system.json')
    run_setup(save_config, '/usr/local/share/adi/your_config.json')
    run_setup(save_run, options['install'] + '/usr/local/share/adi/your_system.json')
    run_setup(save_config, options['install'] + '/usr/local/share/adi/your_config.json')

    return True


def scripts() -> bool:
    echo("Current scripts queue: " + str(process['needed_system_scripts']))
    for script in set(process['needed_system_scripts']):
        run_setup(eval(script))
        options['installed_system_scripts'].append(script)
    return True


def script_booster_uki() -> bool:
    echo("UKI Generation script will be installed to /usr/local/share/adi/scripts")
    echo("UKI Generation Pacman Hook will be installed to /etc/pacman.d/hooks")
    process['needed_script_packages'] += ['python', 'binutils', 'systemd']

    run_command('mkdir', ['-p', options['install']+"/usr/local/share/adi/scripts"])
    run_command('mkdir', ['-p', options['install'] + "/etc/pacman.d/hooks"])
    run_command('cp', ['-f', 'hooks/99-adi-uki.hook', options['install']+"/etc/pacman.d/hooks/"])
    run_command('cp', ['-f', 'scripts/uki', options['install'] + "/usr/local/share/adi/scripts/"])
    run_command('chmod', ['+x', options['install'] + "/usr/local/share/adi/scripts/uki"])
    return True


def script_hfp_ofono() -> bool:
    echo("Sorry! Not implemented yet! I have troubles with PKGBUILDing.")
    return True


def script_packages() -> bool:
    echo("Additional packages will be installed: " + str(process['needed_script_packages']))
    packages = list(set(process['needed_script_packages']) - set(options['configData']['packages']))
    install_pacstrap(packages)
    options['installed_script_packages'] += packages
    return True


if __name__ == "__main__":
    run_setup(parse_options, sys.argv[1:])
    run_setup(read_config)

    try:
        setup_first_index = process['setup_chain'].index(process['first_setup'])
    except ValueError:
        echo("No such chain! Will start from first setup!")
        setup_first_index = 0

    echo("Current setup chain: " + str(process['setup_chain'][setup_first_index:]))

    time.sleep(5)

    for setup in process['setup_chain'][setup_first_index:]:
        run_setup(eval(setup))
