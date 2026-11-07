# Fase 0 — kernel 4.19 no Moto G6 Plus (evert)

Pacote de teste do forward-port do kernel **4.19.325-cip136** para o
Moto G6 Plus (`evert`, SDM630). O objetivo é validar o boot no hardware
real e o caminho RPM/GLINK/SMEM/reguladores. **Não é uma ROM instalável.**

## Arquivos

| Asset | Tamanho | SHA256 |
|---|---:|---|
| `boot-4.19-evert-test-mini.img` | 17,8 MB | `68aa4e2cfeedaac2715ebec9241f95a93703b9e6f5b905ed715008065344582b` |
| `boot-4.19-evert-test-patched-dtb.img` | 32,8 MB | `b17637872b39c567277a34dd2b66cce3953b0cd998927003307f15a57f1ae025` |
| `kernel-4.19-evert-patched.gz` | 17,6 MB | `eed15098ddb7612161a930baf0fc0a23e591beab2ddffb7a71d028f7f65794c8` |
| `boot.img` (repack LOS, não backup stock) | 30,6 MB | `08eccfdd619e180b6f27a80eb2844f54f3002bf9f610ebf74b834813cf3391d9` |
| `phase0-test.tar` | 98,8 MB | `1d1359dbfd6880c584fb0b59eb1fc2db58c291f6c1ff4ec85418ce9b0c1f29fa` |
| `SHA256SUMS-phase0.txt` | — | checksums das 3 imagens de teste |
| `stock-kernel-4.4.gz-dtb` (opcional, rebuild) | 15,3 MB | `7287ea1371da5dcf7c594d431bee1e25647695eb9ffc889f96d20ae449946a33` |
| `stock-ramdisk-lines-22.2.img` (opcional, rebuild) | 15,3 MB | `703b873c3b2b898a55183d5a27702bed48a9a49becb8c3d59d944a3d50398b90` |

## Teste rápido

```sh
# 1. baixar os assets
gh release download v0.1-phase0 -R CarlosRgoku/evert-forward-port -D evert-phase0
cd evert-phase0

# 2. conferir
sha256sum -c SHA256SUMS-phase0.txt

# 3. bootloader
fastboot devices

# 4. teste principal (não grava nada)
fastboot boot boot-4.19-evert-test-mini.img
```

O mini-init grava `EVERT-4.19-MINI-INIT OK` em `/dev/kmsg` e reinicia em
~8 s. Se o aparelho voltar ao Android, o kernel 4.19 chegou ao userspace.

Depois, leia o pstore no Android stock/LOS 4.4:

```sh
adb shell su -c 'cat /sys/fs/pstore/console-ramoops*'
adb shell su -c 'cat /sys/fs/pstore/dmesg-ramoops*'
```

O teste secundário usa o ramdisk do LineageOS 22.2:

```sh
fastboot boot boot-4.19-evert-test-patched-dtb.img
```

Não flashar: a imagem tem 32,8 MB e pode não caber na partição `boot`.

## Limitações conhecidas

- **Console UART inerte.** `CONFIG_SERIAL_MSM` e
  `CONFIG_SERIAL_MSM_CONSOLE` estão desligados; `console=ttyMSM0` e
  `earlycon` não fazem nada. O diagnóstico é via pstore. Veja
  `REBUILD.md` para habilitar a UART.
- **`boot.img` não é backup de fábrica.** É um repack do kernel 4.4 stock
  + ramdisk do LOS 22.2, sem footer AVB. Faça backup real da partição
  `boot` (e `vbmeta`) antes de qualquer flash.
- **`mini-init` defasado.** A imagem publicada usa um binário anterior ao
  fonte atual, sem `MINI_INIT_BUILD_ID`. O marcador `OK` continua válido.
- **Teste 2 pode falhar por ABI de vendor.** Os blobs do Android 15 foram
  feitos para o kernel 4.4.
- **DTB adaptado só para RPM/GLINK/SMEM/TCSR/ramoops.** Display, touch,
  câmera e GPIO do PMIC podem não funcionar nesta fase.

## Rebuild

O código, os scripts e os DTBs estão no repositório. As instruções
completas estão em `REBUILD.md`. O kernel usado é
`LineageOS/android_kernel_qcom_sdm660`, branch `lineage-20`, commit
`6c095591a5c`; o toolchain é o ARM GNU 8.3-2019.03.

## Licença

Kernel e scripts em GPL-2.0. O ramdisk do LineageOS 22.2 e as imagens de
boot podem conter componentes com outras licenças. Veja `LICENSE` e
`NOTICE`.
