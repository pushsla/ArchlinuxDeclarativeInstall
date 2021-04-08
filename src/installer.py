#!/usr/bin/python
import json
import sys
import getopt
import subprocess
import time

process = {
    'logfile': 'adi.log',
    'log_depth': 0,
    'satisfied': True,
    'first_setup': 'configure_filesystems',
    'setup_chain': [
        'configure_filesystems',
        'install_world',
        'install_kernel',
        'configure_userspace',
        'configure_world',
        'configure_boot'
    ],
}

options = {
    'install': "/mntarch",
    'root_uuid': "",
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


def run_command(cmd: str, args: list, nofail=False) -> int:
    process['log_depth'] += 1
    args = list(filter(lambda x: x != "", args))
    echo('EXEC: ', cmd + ' ' + ' '.join(args))
    with open(process['logfile'], 'a') as log:
        log.write("<CommandOutput>\n")
        p = subprocess.Popen(' '.join([cmd] + args), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = p.wait()
        output, err = p.communicate()
        log.write(output.decode('utf-8'))
        log.write("\n<Error>\n"+err.decode('utf-8')+"</Error>\n")
        if err:
            print(err.decode('utf-8'))
        #result = 0
        log.write("\n</CommandOutput>\n")
    if not nofail and result != 0:
        raise Exception('  ' * process['log_depth'] + "Command Error!")
    process['log_depth'] -= 1
    return result


def run_chroot(cmd: str, args: list, nofail=False) -> (int, str):
    run_command("arch-chroot", [options['install'], cmd] + args, nofail=nofail)


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


def parse_options(argv: list) -> bool:
    try:
        options['params'], options['arguments'] = getopt.getopt(argv, "c:i:s:", ['config=', 'install=', 'setup='])
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
                mounts.append(part)
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
    run_command('pacstrap', [options['install']] + options['configData']['packages'])

    if options['configData']['system']['bootloader']['install_bootloader']:
        run_command('pacstrap', [options['install'], options['configData']['system']['bootloader']['used_bootloader']])
    return True


def install_kernel() -> bool:
    run_command('pacstrap', [options['install'], options['configData']['system']['initram']])
    run_command('pacstrap', [options['install'], options['configData']['system']['kernel'],
                             options['configData']['system']['ucode']])
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
    run_chroot('passwd', ['root'])

    return True


def configure_userspace() -> bool:
    users = options['configData']['system']['users']
    for user in users:
        home = ["-m"] if user['home'] else []
        groups = ["-G", ','.join(user['groups'])] if user['groups'] else []
        shell = ["-s", user['shell']] if user['shell'] else []

        run_chroot('useradd', home + groups + shell + [user['name']], nofail=True)
        echo("Configure {}`s password (safe UNIX passwd command used. Enter password Twice!):".format(user['name']))
        run_chroot('passwd', [user['name']])

    run_command('pacstrap',
                [options['install'], options['configData']['system']['desktop'], options['configData']['system']['dm']])
    run_chroot('systemctl', ['enable', options['configData']['system']['dm']])

    return True


def configure_boot() -> bool:
    echo("Currenlty supported image generators are: booster")
    echo("Currenlty supported bootloaders are: refind")

    system = options['configData']['system']
    bootloader = system['bootloader']

    if bootloader['install_bootloader']:
        if bootloader['used_bootloader'] == "refind":
            run_chroot('refind-install', [])
        else:
            echo("I have no idea what to do with this bootloader! You have to configure it and EFISTUB manually!")

    if system['initram'] == 'booster':
        run_setup(boot_booster)
    else:
        echo("I have no idea what to do with this initrd generator! You have to configure it and EFISTUB manually!")

    return True


def boot_efistub(kernel: str, initram: str, ucode: str = None) -> bool:
    echo("Currently supported EFISTUB types: UnifiedKernelImage")
    system = options['configData']['system']
    bootloader = system['bootloader']

    run_command('mkdir', ['-p', options['install'] + bootloader['efistub_dir']])

    if read('Would you like to create Unified Kernel image? [Y/n]') in ('Y', 'y', ''):
        cmdline = read("Specify kernel cmdline parameters (dont leave empty! 'rw' and 'root=' required!): ")
        run_chroot('echo',
                   ['\"{}\"'.format(cmdline), '>', options['install'] + '/etc/kernel/cmdline-' + system['kernel']])

        if ucode:
            run_chroot('cat', [ucode, initram, '>', ''.join(initram.split('.')[:-1]) + "-" + system['ucode'] + '.img'])
            ucode = ''.join(initram.split('.')[:-1]) + "-" + system['ucode'] + '.img'

        uki_params = [
            '--add-section .osrel="/usr/lib/os-release" --change-section-vma .osrel=0x20000',
            '--add-section .cmdline="/etc/kernel/cmdline-{}" --change-section-vma .cmdline=0x30000'.format(
                system['kernel']),
            '--add-section .linux="{}" --change-section-vma .linux=0x2000000'.format(kernel),
            '--add-section .initrd="{}" --change-section-vma .initrd=0x3000000'.format(initram),
            '"/usr/lib/systemd/boot/efi/linuxx64.efi.stub" "{}{}.efi"'.format(bootloader['efistub_dir'],
                                                                              system['kernel'])
        ]

        run_chroot('rm', [bootloader['efistub_dir'] + "/" + system['kernel'] + ".efi"])
        run_chroot('objcopy', uki_params)
    else:
        echo("Its OK, but I can only do unified kernel image trick. You have to configure EFISTUB manually then...")

    return True


def boot_booster() -> bool:
    system = options['configData']['system']
    run_chroot('/usr/share/libalpm/scripts/booster-install', ['<<<', "usr/lib/modules/$(uname -r)/vmlinuz"])
    if system['bootloader']['efistub']:
        if system['ucode']:
            run_setup(boot_efistub, "/boot/vmlinuz-" + system['kernel'],
                      '/boot/booster-{}.img'.format(system['kernel']), ucode="/boot/" + system['ucode'] + '.img')
        else:
            run_setup(boot_efistub, "/boot/vmlinuz-" + system['kernel'],
                      '/boot/booster-{}.img'.format(system['kernel']))
    return True


if __name__ == "main":
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
