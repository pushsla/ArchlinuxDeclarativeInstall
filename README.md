# Arch Declarative Install
Script collection for ArchLinux installation replication with power of declarative-like JSON configurations

## Disclaimer
This project was basically evented to satisfy my own installation needs.

So there could be manu bugs with very different configurations. So, test on Virtual Machine first =)

**Any** Bug-reports and pull-requests are appreciated!

## Motivation
It became so annoying for me to boot ArchLinux live iso and **every time** run same commands in the terminal
to get same results on different machines (or on one machine many times).

So, I know that ArchLinux has now (2021-04-04) its own text installer, but I see no difference between typing
commands in console and choosing options in text dialog.

That`s why I have used to write my own installation/configuration automatizator.

## Collection
### Installation
#### Configuration options

Example configuration you can find in /src/worldconfig.json

Detailed config:

##### Hardware
Configurations related to hardware

###### Partitions
List of objects:
* "dev" - String, block-device name, ex. /dev/sda3
* "fs" - String, filesystem type. FAT32 is "vfat", SWAP is "swap", swap will be mounted in any case.
* "fs_options" - String, additional options passed to mkfs
* "mount" - String, path to dir, where device should be mounted. If empty, device will not be mounted. Swap will be mounted in any case, independent from this option.
* "mount_options" - String, additions options passed to mount. Have no effect on devices with "fs": "swap".

Keep in mind, that all paths in "mount" field have to be passed as they should be in real system.

F.ex for root partition "mount": "/", for ESP "mount": "/boot/efi". **Not** "mount": "/mnt" and "mount": "/mnt/boot/efi"

Also you must add one device with mountpoint set to "/", or installer would not install anything =)

All specified partitions would be added to fstab with UUIDs.

##### Packages
List of Strings.

You can add any package from extra/community/multilib repo you want.

But do not hurry with adding kernel/DE/DM packages! There are separate options for them!

##### System
Basic System configuration.
Child options:
* "kernel" - String, linux kernel to use. You can use "linux", "linux-zen" and others
* "initram" - String, Program stat will be used to generate initramfs
* "ucode" - String, microcode package
* "dm" - String, DisplayManader you want to use. Ex. "sddm"
* "desktop" - String, DE you want to use. Ex. "plasma"

Sub-options:
###### Bootloader
Bootloader parameters:
* "efistub" - Bool, do you want to use EFISTUB Unified Kernel Image in your system?
* "efistub_dir" - String, where to put EFISTUB Unified Kernel Image?
* "used_bootloader" - String, name of bootloader you want to use
* "install_bootloader" - Bool, should installer also install your favourive bootloader?

###### Systemd
Systemd parameters:
* "timezone" - String, timezone. Ex: "Europe/Moscow"
* "ntp" - Bool, use NTP?
* "hostname" - String, hostname of your installation
* "locales" - List of String, needed locales
* "main_locale" - String, preferred locale to use in system 

###### Users
Users configuration.
List of objects:
* "name" - String, username
* "groups" - List of String, groups for user
* "shell" - String, path to shell
* "home" - Bool, create homedir?

### Configuration
...coming soon...
## Security
Open-Source =)