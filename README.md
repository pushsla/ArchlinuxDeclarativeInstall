# Arch Declarative Install
Script collection for ArchLinux installation replication with power of declarative-like JSON configurations

## Have fun!
If you find this code useful, I will be glad if you use it in your GPL3-compatible licensed project.

**"Why GPL-3. Author, are you too proud?"**
> Nope. It's just that I'm fighting for free software, and any possibility that someone else is using my code on a project that people, myself included, will have to pay for is unacceptable.
> My code is neither perfect nor revolutionary. But the world is crazy, you know

Any help and criticism is greatly appreciated.

## Disclaimer
This project was basically evented to satisfy my own installation needs.

So there could be manu bugs with very different configurations. So, test on Virtual Machine first =)

With a config sample (you can find in src/worldconfig.json) - 100% works!

Only UIEFI systems are supported

**Any** Bug-reports and pull-requests are appreciated!

## Motivation
It became so annoying for me to boot ArchLinux live iso and **every time** run same commands in the terminal
to get same results on different machines (or on one machine many times).

So, I know that ArchLinux has now (2021-04-04) its own text installer, but I see no difference between typing
commands in console and choosing options in text dialog.

That`s why I have used to write my own installation/configuration automatizator.

## Why goddamn Python? Why not Go or godlike Rust?

Because this script - is a thing that you run once to install system and forget about it.
Compiling - is not the process I expect from this-type insrtument.

## Collection
### Installation
#### Configuration options

Example configuration you can find in /src/worldconfig.json

##### Detailed config:
* **"hardware"** [Obj] Hardware configuration
    * **"partitions"** [List of Obj] Make filesystems and mount partitions. You must make partitions yourself before installation
        * **[List entry]**
            * **"dev"** [Str] partitions block device path. ex "/dev/sda1"
            * **"fs"** [Str] filesystem to mkfs. If empty - will be mounted without 'mkfs'. For FAT32 use 'vfat'
            * **"fs_options"** [Str] filesystem creation options
            * **"mount"** [Str] mountputin path relatively to target system ex. "/boot/efi"
            * **"mount_options"** mount options
* **"packages"** [List of Str] system package names. Also, DM/DE/Kernel/Bootloader packages have to be set in other place of config
* **"aur_packages"** [List of Obj] packages to install from AUR to the target OS
    * **[List entry]**
        * **"name"** [Str] accurate package name in AUR
        * **"deps"** [List of Str] **ALL** package dependencies. You have to solve deps by yourself!
        * **"make_deps"** [List of Str] Deps that needed to make package
        * **"remove_make_deps"** [Bool] if True -- makedeps will be removed after installation
* **"system"** [Obj] System options
    * **"kernels"** [List of Obj] kernels you want to use in system
        * **[List entry]**
            * **"version"** [Str] accurate kernel version ex "linux", "linux-lts", "linux-zen"
            * **"cmdline"** [Str] cmdline that will be used for this kernel
    * **"initram"** [Str] initramfs generator package name. supported ones are: mkinitcpio, booster
    * **"ucode"** [Str] microcode package name. supported: intel-ucode, amd-ucode
    * **"bootloader"** [Obj] boot configurations
        * **"uki"** [Obj] Unified Kernel Image EFISTUB config
            * **"use_uki"** [Bool] if True, UKI will be generated
            * **"gen_dest"** [Str] where to put generated UKI
            * **"add_hook"** [Bool] if True hook and script to re-generate UKI on kernel pupdate will be installed to target OS
        * **"used_bootloader"** [Str] bootloader package name
        * **"install_bootloader"** [Bool] if True, bootloader will be installed to computer. Leave false if there is already one you want to use
    * **"systemd"** [Obj] systemd settions
        * **"timezone"** [Str] timezone name ex "Europe/Moscow"
        * **"ntp"** [Bool] if True NTP will be set to TRUE
        * **"hostname"** [string] hostname for target OS
        * **"locales"** [List of Str] accurate names of needed locales ex "en_US.UTF-8 UTF-8"
        * **"main_locale"** [Str] locale that will be set as main system locale
    * **"dm"** [Str] package name of DisplayManager. It will be enabled automatically.
    * **"desktop"** [Str] package name of used DE base-package. In future there may be additional tricks for differend DE
    * **"users"** [List of Obj] users (except of root) to add to target OS
        * **[List entry]**
            * **"name"** [Str] user name
            * **"groups"** [List of Str] groups of user
            * **"shell"** [Str] used shell path
            * **"home"** [Bool] does user need home dir?
            * **"password"** [Bool] does user need password to be set? (You will set it by yourself in automated mode)
* **"features"** [???] Experimental and not implemented. There will be different tricks and usefull hacks

### Configuration
...coming soon...
## Security
Open-Source =)
