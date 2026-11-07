# Rebuild — do zero até as imagens de teste

Este documento reproduz o build da Fase 0. O kernel e o toolchain **não**
estão versionados neste repositório; baixe-os dos links abaixo.

## Requisitos

- Linux x86_64
- `git`, `make`, `bc`, `bison`, `flex`, `libssl-dev`, `python3`
- `cpio`, `gzip`, `xz`
- `dtc` (o do kernel em `kernel/out/scripts/dtc/dtc` é o mais fiel)
- ARM GNU Toolchain **8.3-2019.03** (`aarch64-linux-gnu-gcc` 8.3.0)
- AArch64 glibc estática (para o `mini-init` estático)

No Arch Linux, o toolchain usado foi:

```sh
sudo pacman -S --needed aarch64-linux-gnu-gcc aarch64-linux-gnu-glibc
```

O tarball oficial equivalente é
`gcc-arm-8.3-2019.03-x86_64-aarch64-linux-gnu.tar.xz` (ARM Developer).

## 1. Kernel 4.19

```sh
git clone https://github.com/LineageOS/android_kernel_qcom_sdm660.git kernel
cd kernel
git checkout 6c095591a5c61c54f2a0b4902cf2c3fcaecf49bd
```

O commit usado no build foi
`6c095591a5c61c54f2a0b4902cf2c3fcaecf49bd` (branch `lineage-20`).
A versão final é `4.19.325-cip136-st20-perf-g6c095591a5c6`.

Configure e compile:

```sh
export ARCH=arm64
export CROSS_COMPILE="$PWD/../toolchains/gcc83/bin/aarch64-linux-gnu-"

make O=out ARCH=arm64 sdm660-perf_defconfig

# Opcional: habilitar o console UART (recomendado para depuração)
./scripts/config --file out/.config -e SERIAL_MSM -e SERIAL_MSM_CONSOLE
make O=out ARCH=arm64 olddefconfig

make O=out ARCH=arm64 -j"$(nproc)"
```

Saída:

```text
out/arch/arm64/boot/Image
out/arch/arm64/boot/Image.gz
```

O `Image.gz` deste build tem 15.981.135 bytes. O `Image` tem 40.843.272
bytes e a string de versão
`Linux version 4.19.325-cip136-st20-perf-g6c095591a5c6`.

> `sdm660-perf_defconfig` não habilita `SERIAL_MSM`/`SERIAL_MSM_CONSOLE`.
> O `sdm660_defconfig` habilita, mas foi usado o `-perf` para ficar fiel ao
> build original. Se quiser UART, use os dois `scripts/config` acima.

## 2. DTBs patchados

Os 5 DTBs stock estão em `boot/dtb0.img` … `boot/dtb4.img`. O script
`tools/patch_evert_rpm.py` adapta o DTS decompilado aos bindings 4.19.

```sh
DTC=kernel/out/scripts/dtc/dtc
for i in 0 1 2 3 4; do
    "$DTC" -I dtb -O dts -o "/tmp/evert$i.dts" "boot/dtb$i.img"
    python3 tools/patch_evert_rpm.py "/tmp/evert$i.dts" "/tmp/evert$i-4.19.dts"
    "$DTC" -I dts -O dtb -o "/tmp/evert$i-4.19.dtb" "/tmp/evert$i-4.19.dts"
done
```

Os arquivos já gerados estão em `dts-patch/`:

```text
dts-patch/evert0.dts … evert4.dts            # stock decompilado
dts-patch/evert0-4.19.dts … evert4-4.19.dts  # patchado
dts-patch/evert0-4.19.dtb … evert4-4.19.dtb  # binário final
```

Os 5 DTBs têm `qcom,board-id` e `qcom,msm-id` iguais aos stock. O
bootloader escolhe a variante correta pelo board ID.

## 3. Concatenar kernel + DTBs

O boot header v0 do evert não tem campo `dtb`; os DTBs vão anexados ao
final do `Image.gz`, como no kernel stock 4.4.

```sh
cat kernel/out/arch/arm64/boot/Image.gz \
    dts-patch/evert0-4.19.dtb \
    dts-patch/evert1-4.19.dtb \
    dts-patch/evert2-4.19.dtb \
    dts-patch/evert3-4.19.dtb \
    dts-patch/evert4-4.19.dtb \
    > kernel-4.19-evert-patched.gz
```

Conferência rápida:

```sh
gzip -t kernel-4.19-evert-patched.gz
# "decompression OK, trailing garbage ignored" é esperado: os DTBs são o
# "trailing garbage" depois do membro gzip do kernel.
```

O arquivo final tem 17.556.357 bytes (15.981.135 do `Image.gz` +
1.575.222 dos 5 DTBs).

## 4. mini-init e ramdisk mínimo

```sh
BUILD_ID="phase0-$(date +%Y%m%d)"
aarch64-linux-gnu-gcc -std=gnu11 -static -Os -Wall -Wextra -Werror \
    -DMINI_INIT_BUILD_ID="\"$BUILD_ID\"" \
    tools/mini-init.c -o mini-init

file mini-init   # ELF 64-bit ARM aarch64, statically linked
```

O `-DMINI_INIT_BUILD_ID="\"$BUILD_ID\""` é necessário para passar uma
**string** ao C, não um identificador.

Monte o initramfs:

```sh
root=$(mktemp -d)
install -d -m 0755 "$root"/{dev,proc,sys}
install -m 0755 mini-init "$root/init"

(cd "$root" && find . -print0 |
    LC_ALL=C sort -z |
    cpio --null -o -H newc --owner=0:0) |
    gzip -n -9 > mini-ramdisk.img
```

O `mini-init` cria `/dev/console`, `/dev/kmsg` e `/dev/null` com `mknod`
(porque `CONFIG_DEVTMPFS` está off), monta `proc`/`sysfs`, imprime o
marcador e reinicia em 8 s.

## 5. Empacotar a imagem mini

Use o `mkbootimg` já patchado deste repositório. O header do evert é v0,
page size 4096, kernel offset `0x8000`, ramdisk offset `0x1000000`, tags
offset `0x100`.

```sh
python3 tools/mkbootimg/mkbootimg.py \
    --header_version 0 \
    --base 0 \
    --pagesize 4096 \
    --kernel_offset 0x8000 \
    --ramdisk_offset 0x1000000 \
    --tags_offset 0x100 \
    --board '' \
    --cmdline 'androidboot.hardware=qcom ehci-hcd.park=3 lpm_levels.sleep_disabled=1 service_locator.enable=1 swiotlb=2048 androidboot.configfs=true sched_enable_hmp=1 sched_enable_power_aware=1 androidboot.usbcontroller=a800000.dwc3 loop.max_part=7 androidboot.veritymode=eio androidboot.boot_devices=soc/c0c4000.sdhci console=ttyMSM0,115200n8 earlycon ignore_loglevel loglevel=8 panic=10' \
    --kernel kernel-4.19-evert-patched.gz \
    --ramdisk mini-ramdisk.img \
    --os_version 15.0.0 \
    --os_patch_level 2026-10 \
    --output boot-4.19-evert-test-mini.img
```

O `mkbootimg-phase0.patch` documenta as mudanças feitas no `mkbootimg`
upstream (aceitar `-o` como caminho, staging atômico, etc.). O
`tools/mkbootimg/mkbootimg.py` do repositório já está patchado.

## 6. Empacotar a imagem com o ramdisk do LineageOS 22.2

Baixe `ramdisk-lines-22.2.img` da release (ou use o `boot/ramdisk.img` do
seu build do LOS 22.2) e empacote:

```sh
python3 tools/mkbootimg/mkbootimg.py \
    --header_version 0 \
    --base 0 \
    --pagesize 4096 \
    --kernel_offset 0x8000 \
    --ramdisk_offset 0x1000000 \
    --tags_offset 0x100 \
    --board '' \
    --cmdline 'androidboot.hardware=qcom ehci-hcd.park=3 lpm_levels.sleep_disabled=1 service_locator.enable=1 swiotlb=2048 androidboot.configfs=true sched_enable_hmp=1 sched_enable_power_aware=1 androidboot.usbcontroller=a800000.dwc3 loop.max_part=7 androidboot.veritymode=eio androidboot.boot_devices=soc/c0c4000.sdhci androidboot.selinux=permissive console=ttyMSM0,115200n8 earlycon' \
    --kernel kernel-4.19-evert-patched.gz \
    --ramdisk ramdisk-lines-22.2.img \
    --os_version 15.0.0 \
    --os_patch_level 2026-10 \
    --output boot-4.19-evert-test-patched-dtb.img
```

Essa imagem tem ~32,8 MB. **Não flashar**; use `fastboot boot`.

## 7. Verificar

```sh
python3 tools/mkbootimg/unpack_bootimg.py \
    --boot_img boot-4.19-evert-test-mini.img --out /tmp/unpacked-mini

sha256sum -c boot/SHA256SUMS-phase0.txt
```

O `unpack_bootimg.py` mostra header v0, page 4096, kernel/ramdisk sizes e
a cmdline. O `tools/dtb_dump.py` lista os DTBs anexados e as propriedades
`qcom,board-id`/`qcom,msm-id`.

## 8. Recriar o `phase0-test.tar` (opcional)

```sh
mkdir -p /tmp/phase0-tar
cp PHASE0-README.md /tmp/phase0-tar/
cp -a boot /tmp/phase0-tar/
# remova do tar o que não deve ir (ex.: obsolete/)
tar -C /tmp/phase0-tar -cf phase0-test.tar PHASE0-README.md boot
sha256sum phase0-test.tar > phase0-test.tar.sha256
```

O tar publicado inclui `PHASE0-README.md`, as duas imagens de teste, o
`kernel-4.19-evert-patched.gz`, o `boot.img` e o
`SHA256SUMS-phase0.txt`.
