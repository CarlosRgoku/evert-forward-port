# Fase 0 — kernel 4.19 no evert (sem flash)

Objetivo: validar, com o menor risco possível, se o kernel 4.19 da base
`LineageOS/android_kernel_qcom_sdm660` (4.19.325-cip136) inicia no Moto G6 Plus
(`evert`, SDM630) e se o RPM/GLINK/SMEM funcionam com o hardware real.

O boot stock 4.4 **não foi alterado**. Nada aqui precisa ser gravado na
partição `boot`; todos os testes usam `fastboot boot` (carrega a imagem na RAM).

## Kernel usado

- `4.19.325-cip136-st20-perf-g6c095591a5c6`
- Base: `LineageOS/android_kernel_qcom_sdm660`, branch `lineage-20`
- BPF 5.10 backport já presente
- `CONFIG_BPF_SYSCALL`, `CONFIG_BPF_JIT`, `CONFIG_BPF_JIT_ALWAYS_ON`,
  `CONFIG_BPF_LSM`, `CONFIG_CGROUP_BPF`, `CONFIG_FUSE_BPF`,
  `CONFIG_NET_CLS_BPF`, `CONFIG_NET_ACT_BPF`,
  `CONFIG_NETFILTER_XT_MATCH_BPF` = `y`
- `CONFIG_PSTORE`, `CONFIG_PSTORE_RAM`, `CONFIG_PSTORE_CONSOLE`,
  `CONFIG_PSTORE_PMSG` = `y` (para recuperar o log depois de um panic)
- `CONFIG_DEBUG_INFO_BTF` ainda não está setado (não é necessário para o boot;
  pode ser necessário depois para CO-RE/netd)

## Imagens

Copie a pasta `boot/` para o host que tem `fastboot` e o evert e entre nela
(`cd boot`). Os comandos de teste abaixo usam os nomes dos arquivos dentro
dessa pasta.

| Arquivo | Tamanho | Uso |
|---|---:|---|
| `boot/boot-4.19-evert-test-mini.img` | 17,8 MB | **Teste principal.** Kernel + 5 DTBs patchados + initramfs mínimo. Imprime status, reinicia em ~8 s. |
| `boot/boot-4.19-evert-test-patched-dtb.img` | 32,8 MB | Kernel + 5 DTBs patchados + ramdisk stock LineageOS 22.2. Tenta subir o Android. |
| `boot/boot.img` | 30,6 MB | Repack do kernel 4.4 stock + ramdisk LOS 22.2. **Não é backup de fábrica.** |
| `boot/kernel-4.19-evert-patched.gz` | 17,6 MB | `Image.gz` 4.19 + os 5 DTBs patchados. |
| `boot/SHA256SUMS-phase0.txt` | — | Checksums das imagens de teste. |
| `dts-patch/evert0-4.19.dtb` … `evert4-4.19.dtb` | 308 KB cada | DTBs stock patchados, um por variante de placa. |

`SHA256SUMS-phase0.txt` usa nomes relativos; rode `sha256sum -c` dentro de
`boot/`.

`boot/obsolete/` guarda a imagem intermediária com os DTBs stock **não**
patchados e artefatos antigos. Não usar.

## O que foi mudado nos DTBs

Os 5 DTBs stock do evert foram decompilados e patchados apenas no plumbing que
mudou entre 4.4 e 4.19; o hardware em si (painel, touch, câmera, reguladores,
eMMC, USB, board IDs) continua descrito pelo DTB stock.

- RPM legado `qcom,rpm-glink` → `qcom,glink-rpm` + `qcom,rpm-smd` (rpmsg)
- `qcom,smem`: adicionado `memory-region` e `hwlocks`
- Adicionado `syscon@1f40000` + `qcom,tcsr-mutex` para o hwlock do SMEM
- Adicionado `mailbox@17911000` (`qcom,sdm660-apcs-hmss-global`) para o GLINK
- Adicionado `rpm-msg-ram@778000` (`qcom,rpm-msg-ram`)
- O transporte RPM antigo `qcom,glink-rpm-native-xprt` foi desabilitado
- `ramoops`: adicionado `reg = <0xaf000000 0xc0000>` e tamanhos de 32 bits
  (`console-size`, `record-size`, `pmsg-size`) para o driver 4.19
- `qcom,board-id`, `qcom,msm-id`, `model` e `compatible` foram preservados

O `ramoops` stock (`0xaf000000`, `0xc0000`) também foi mantido, mas o nó foi
adaptado ao binding do driver 4.19: o driver 4.4 usa `memory-region` e tamanhos
de 64 bits, enquanto o 4.19 usa `reg` e tamanhos de 32 bits. Sem esse ajuste o
pstore do 4.19 não registrava. O layout de tamanhos é o mesmo do stock 4.4,
então o console buffer deve ser legível no boot seguinte; o DTB patch não
persiste no `fastboot boot` — o 4.4 usa o DTB stock dele.

## Teste 1 — imagem mini (recomendado)

1. No PC com `fastboot`, dentro da pasta `boot/`:
   ```sh
   sha256sum -c SHA256SUMS-phase0.txt
   ```
2. Coloque o evert no bootloader:
   ```sh
   adb reboot bootloader
   # ou desligue e segure Vol- + Power
   ```
3. Confirme:
   ```sh
   fastboot devices
   ```
4. **Não flashar.** Carregue só na RAM:
   ```sh
   fastboot boot boot-4.19-evert-test-mini.img
   ```
5. O que observar:
   - Se o aparelho reiniciar sozinho para o Android em ~8 s, o kernel 4.19
     chegou ao userspace (mini-init rodou).
   - Se reiniciar em ~10 s sem chegar ao Android, provavelmente houve panic;
     o pstore deve ter o log.
   - Se ficar parado/tela preta, segure Power por ~10 s para reiniciar.
   - O mini-init grava `EVERT-4.19-MINI-INIT OK` em `/dev/kmsg`; o pstore
     captura esse marcador. O console UART só funciona após habilitar
     `CONFIG_SERIAL_MSM`/`CONFIG_SERIAL_MSM_CONSOLE` (veja a seção de
     riscos).

Se o `fastboot boot` for recusado, **pare** e copie a mensagem exata. Não
flashar sem backup.

## Ler o pstore depois do teste

Depois que o evert voltar ao Android stock 4.4:

```sh
adb shell su -c 'ls -l /sys/fs/pstore'
adb shell su -c 'cat /sys/fs/pstore/console-ramoops*'
adb shell su -c 'cat /sys/fs/pstore/dmesg-ramoops*'
```

- Se `su` não existir, tente `adb root` (só funciona em build userdebug).
- Se não houver root, o log pode ser lido por recovery com shell root, ou
  podemos preparar uma imagem mini com USB serial para capturar sem Android.
- O marcador `EVERT-4.19-MINI-INIT OK` do mini-init aparece no
  `console-ramoops` se o kernel chegou ao userspace.
- O `ramoops` sobrevive a reset quente; desligar a bateria pode apagar.
- Envie o log completo (não só o final); ele diz exatamente em qual driver o
  kernel 4.19 parou.

## Teste 2 — ramdisk stock (só depois do teste 1)

```sh
fastboot boot boot-4.19-evert-test-patched-dtb.img
```

Essa imagem usa o ramdisk real do LineageOS 22.2, com
`androidboot.selinux=permissive`. O console UART **não** está habilitado
nesta config (`CONFIG_SERIAL_MSM` desligado). Se o Android subir,
temos adb; se travar, o pstore do próximo boot stock deve ter o log. Ela tem
32,8 MB; **não flashar** (pode não caber na partição `boot`).

## Riscos e limitações desta fase

- O DTB stock 4.4 só foi adaptado para RPM/GLINK/SMEM/TCSR/ramoops. Outros
  bindings 4.4 podem não casar com os drivers 4.19: GPIO do PMIC
  (`qcom,qpnp-pin` vs `qcom,spmi-gpio`), painel/touch Motorola, câmera, etc.
- É esperado o kernel chegar ao userspace e talvez **não** ter display, touch
  ou Android completo. Isso ainda é sucesso de Fase 0.
- O ramdisk stock é de Android 15 e os blobs vendor foram feitos para o kernel
  4.4; o teste 2 pode falhar por ABI de vendor, não por falta de suporte do
  kernel.
- O teste mini usa `panic=10`, então um panic reinicia sozinho.
- O binário `tools/mini-init` usado nas imagens é anterior ao fonte e não
  tem `MINI_INIT_BUILD_ID`; o marcador `OK` continua válido.
- `CONFIG_SERIAL_MSM`/`CONFIG_SERIAL_MSM_CONSOLE` estão desligados; a
  cmdline `console=ttyMSM0`/`earlycon` é inerte. Para UART, rebuildar com
  as duas opções.
- `fastboot boot` em bootloader desbloqueado normalmente aceita imagem sem
  AVB; o boot stock baixado não tem footer AVB. Se o bootloader recusar,
  precisamos de outra estratégia (flash com backup, ou assinatura).

## Próximo passo depois do log

1. Se o mini-init rodar: o básico (CPU, RPM, reguladores, SMEM)
   funciona. Seguir para o DTS próprio do evert e portar display/touch.
2. Se parar antes do init: usar o log do pstore para corrigir o binding
   específico (RPM, SMEM, eMMC, UART, etc.).
3. Se o pstore vier vazio ou ilegível: preparar a variante com USB serial ou
   UART física; se o registro do 4.19 não for legível pelo driver 4.4,
   portar o driver de pstore ou capturar no próprio 4.19.
4. Só depois disso entrar em Android/vendor e validar BPF/netd.

## Arquivos de referência

- Fonte 4.19: `kernel/` (clone de
  `LineageOS/android_kernel_qcom_sdm660`, commit `6c095591a5c`)
- Fonte 4.4 do evert: repositório público do LineageOS/Motorola
- Device tree do evert: repositório público do LineageOS
- Script de patch dos DTBs: `tools/patch_evert_rpm.py`
- Dump/parse de DTB: `tools/dtb_dump.py`
- Init mínimo: `tools/mini-init.c`
- Empacotador: `tools/mkbootimg/mkbootimg.py`
