# Fase 0 — kernel 4.19 no Moto G6 Plus (evert)

Forward-port experimental do kernel **4.19.325-cip136** para o Moto G6 Plus
(`evert`, SDM630), baseado em `LineageOS/android_kernel_qcom_sdm660`
(branch `lineage-20`, commit `6c095591a5c`).

O objetivo desta fase é validar se o kernel 4.19 chega ao userspace no
hardware real e se RPM/GLINK/SMEM/reguladores funcionam. **Não é uma ROM
instalável** e não substitui o kernel stock 4.4.

## Download rápido

Os binários prontos estão na release:

<https://github.com/CarlosRgoku/evert-forward-port/releases/tag/v0.1-phase0>

```sh
gh release download v0.1-phase0 -R CarlosRgoku/evert-forward-port -D evert-phase0
cd evert-phase0
sha256sum -c SHA256SUMS-phase0.txt
```

Ou baixe o pacote completo `phase0-test.tar`, extraia e siga o
`PHASE0-README.md`.

## Teste (sem flashar)

1. Confirme que o bootloader está desbloqueado e o aparelho aparece:

   ```sh
   fastboot devices
   ```

2. **Teste principal** — kernel + 5 DTBs patchados + initramfs mínimo:

   ```sh
   fastboot boot boot-4.19-evert-test-mini.img
   ```

   O mini-init grava `EVERT-4.19-MINI-INIT OK` em `/dev/kmsg` e reinicia
   em ~8 s. Se o aparelho voltar ao Android, o kernel 4.19 chegou ao
   userspace.

3. **Teste secundário** — kernel 4.19 + ramdisk do LineageOS 22.2:

   ```sh
   fastboot boot boot-4.19-evert-test-patched-dtb.img
   ```

   Não flashar: a imagem tem 32,8 MB e pode não caber na partição `boot`.

## Ler o pstore

Depois do teste, o aparelho volta ao Android stock/LOS 4.4. Leia:

```sh
adb shell su -c 'ls -l /sys/fs/pstore'
adb shell su -c 'cat /sys/fs/pstore/console-ramoops*'
adb shell su -c 'cat /sys/fs/pstore/dmesg-ramoops*'
```

O marcador do mini-init aparece no `console-ramoops`. Leia logo após o
teste: o boot do kernel 4.4 grava no mesmo buffer e pode sobrescrever o
final do log.

## Limitações conhecidas

- **Console UART não habilitado.** A config atual tem `CONFIG_SERIAL_MSM_HS=y`
  (UART HS de Bluetooth), mas `CONFIG_SERIAL_MSM` e
  `CONFIG_SERIAL_MSM_CONSOLE` estão desligados. `console=ttyMSM0` e
  `earlycon` são inertes. O diagnóstico é via pstore. Para UART, rebuildar
  com as duas opções (veja `REBUILD.md`).
- **`boot.img` não é backup de fábrica.** É um repack do kernel 4.4 stock +
  ramdisk do LOS 22.2, sem footer AVB. Antes de qualquer flash, faça backup
  real da partição `boot` (e `vbmeta`) via recovery/root com `dd`.
- **`tools/mini-init` está defasado** em relação ao `mini-init.c` (o binário
  não tem `MINI_INIT_BUILD_ID`). A imagem publicada usa o binário antigo;
  o marcador `OK` continua válido. Rebuildar se quiser o build ID.
- **O teste 2 pode falhar por ABI de vendor.** Os blobs do Android 15 foram
  feitos para o kernel 4.4; o kernel 4.19 pode não conversar com todos eles.
  Isso não é necessariamente falha de boot do kernel.
- **DTB adaptado só para o plumbing 4.4→4.19** (RPM/GLINK/SMEM/TCSR/ramoops).
  GPIO do PMIC, painel, touch, câmera e outros bindings 4.4 podem não casar
  com os drivers 4.19.
- **`fastboot boot` da imagem patched** pode ser recusado pelo tamanho
  (32,8 MB). Se acontecer, use a mini.

## O que está no repositório

- `PHASE0-README.md` — guia detalhado da fase 0 (corrigido).
- `REVIEW.md` — revisão técnica do pacote, achados e recomendações.
- `REBUILD.md` — como reconstruir kernel, DTBs, mini-init e imagens.
- `dts-patch/` — DTS stock e patchados, DTBs e logs do `dtc`.
- `boot/dtb*.img` — os 5 DTBs stock usados como entrada.
- `boot/SHA256SUMS-phase0.txt` — checksums dos binários.
- `tools/` — `patch_evert_rpm.py`, `mini-init.c`, `dtb_dump.py` e o
  `mkbootimg` usado (com `mkbootimg-phase0.patch`).
- `build2.log` — build 4.19 bem-sucedido (452 warnings, 0 erros).
- `build.log` — build antigo que falhou em `walt.h`; mantido só como
  referência histórica.

## Rebuild

Veja `REBUILD.md`. Resumo:

- kernel: `LineageOS/android_kernel_qcom_sdm660`, branch `lineage-20`,
  commit `6c095591a5c`;
- toolchain: ARM GNU 8.3-2019.03 (`aarch64-linux-gnu-gcc` 8.3.0);
- defconfig: `sdm660-perf_defconfig`;
- DTBs: `tools/patch_evert_rpm.py` + `dtc`;
- mini-init: `aarch64-linux-gnu-gcc -static`;
- boot image: `tools/mkbootimg/mkbootimg.py`, header v0, page 4096.

## Licença

O kernel é GPL-2.0 (com a exceção de syscall do Linux). Os scripts deste
repositório são GPL-2.0. O ramdisk do LineageOS 22.2 e as imagens de boot
podem conter componentes com outras licenças; verifique antes de
redistribuir. Veja `LICENSE` e `NOTICE`.
