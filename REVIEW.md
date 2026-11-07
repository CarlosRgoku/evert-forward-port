# Revisão técnica — pacote Fase 0 (kernel 4.19 no evert)

Revisão feita antes da publicação da release `v0.1-phase0`. O objetivo foi
verificar se o pacote de teste está correto e se o kernel 4.19 tem chance de
dar boot no Moto G6 Plus (`evert`, SDM630).

## Veredito

O pacote está tecnicamente consistente. O kernel embutido nas imagens é
byte-idêntico ao `Image` gerado pelo build, os 5 DTBs anexados conferem com
os DTBs patchados e os board IDs/msm-ids são iguais aos stock. Não foi
encontrado erro estrutural óbvio que impeça o boot.

Os problemas encontrados são de **diagnóstico e recuperação**, não de boot:

1. o console UART está inerte na config atual;
2. o `boot/boot.img` não é um backup stock de fábrica.

A maior incerteza técnica é o caminho RPM/GLINK/SMEM/reguladores, que só o
hardware real confirma.

## Alta prioridade

### 1. `console=ttyMSM0` e `earlycon` não funcionam

Config efetiva:

```text
# CONFIG_SERIAL_MSM is not set
# CONFIG_SERIAL_MSM_CONSOLE is not set
CONFIG_SERIAL_MSM_HS=y
```

`CONFIG_SERIAL_MSM_HS` é o driver da UART de alta velocidade (Bluetooth).
O `earlycon` do `qcom,msm-uartdm` está em `msm_serial.c`, que não é compilado
sem `SERIAL_MSM`. Portanto `console=ttyMSM0,115200n8 earlycon` é inerte.

O nó `serial@0c170000` está `status = "ok"`, com clocks e pinctrl, e
`/chosen/stdout-path = "serial0"`. Basta habilitar:

```text
CONFIG_SERIAL_MSM=y
CONFIG_SERIAL_MSM_CONSOLE=y
```

O `sdm660_defconfig` já tem as duas; o build usou `sdm660-perf_defconfig`,
que não tem. O kernel stock 4.4 também não tem `SERIAL_MSM`, então isso não
é regressão — é lacuna de teste.

**Impacto:** sem UART, o diagnóstico depende do pstore.

### 2. `boot/boot.img` não é backup stock

Componentes verificados:

- kernel = `boot/stock-reference/kernel.gz-dtb` (4.4), byte-idêntico;
- ramdisk = `boot/ramdisk.img` (LineageOS 22.2), byte-idêntico;
- header v0, sem footer AVB.

É um repack funcional para LOS, não a imagem de fábrica. Se o bootloader
exigir AVB, ele não restaura; se bootar, volta ao LOS, não ao stock.

Antes de qualquer flash, faça backup real da partição `boot` (e `vbmeta`)
via recovery/root com `dd`, e guarde o arquivo fora do aparelho.

### 3. README original superestimava o console

Os trechos “com console habilitado” e “além do console UART” estavam
incorretos com a config atual. O README publicado foi corrigido.

A parte do pstore é plausível: o layout do ramoops (console `0x40000`,
record `0x3f800`, pmsg `0x40000`) é o mesmo do stock 4.4. Mas o DTB patch
não persiste no `fastboot boot`; o 4.4 usa o DTB stock dele. O que sobrevive
é a região de RAM, não o DTB.

Cuidado: o boot do 4.4 grava no mesmo console buffer; se o log do boot stock
for grande, pode sobrescrever o marcador. Leia o pstore logo após o teste.

## Média prioridade

### 4. `tools/mini-init` está defasado

- binário: 27/10 06:24;
- fonte: 07/11 12:01;
- o binário não contém `build=`/`MINI_INIT_BUILD_ID`; o fonte loga isso;
- a imagem mini publicada embute o binário antigo.

Não impede o boot, mas quebra a reprodutibilidade e a identificação do
build. Recomendação: rebuildar com `-DMINI_INIT_BUILD_ID=...`, recriar
`mini-ramdisk.img` e a imagem mini, e atualizar os checksums.

### 5. RPM/GLINK sem filho `qcom,glink-channels`

O patch cria um `rpm-glink` correto (`qcom,glink-rpm`,
`qcom,rpm-msg-ram`, `mboxes = <&apcs_glb 0>`, IRQ 168) e transforma o nó
antigo em `qcom,rpm-smd` com os reguladores.

O driver `qcom_smd_rpm_probe()` acha o nó por
`of_find_compatible_node("qcom,rpm-smd")` e faz `of_platform_populate(p)`,
então os reguladores são populados mesmo sem o filho `rpm_requests`. O canal
rpmsg é criado quando o RPM abre `rpm_requests` (remote-initiated).

Funciona, mas depende desse fallback. O binding moderno pede:

```dts
rpm-requests {
    compatible = "qcom,rpm-smd";
    qcom,glink-channels = "rpm_requests";
};
```

Se o primeiro boot travar cedo por falta de reguladores, é o primeiro lugar
a investigar. Não mexer nisso antes do teste 1; adicionar o filho com o
mesmo compatible pode confundir o `of_find_compatible_node`.

### 6. `ramoops` com `memory-region` + `reg`

O driver 4.19 ignora `memory-region` e `ramoops-annotate-size`; usa `reg` e
tamanhos de 32 bits. O patch está correto e é necessário: o stock tem
`<0x0 0x40000>` (64-bit); `of_property_read_u32` leria `0x0` e
desabilitaria. Com `<0x40000>` lê certo.

A redundância é inofensiva; pode ser limpa depois.

### 7. Overlap `smem-mem@86000000` × `removed_region0@85800000`

Ambos são `no-map` e reservados. A região de 2 MB do smem fica dentro da
região removida de 55 MB. O kernel pode avisar de overlap, mas não deve
quebrar; o smem mapeia só 2 MB. Baixo risco; investigar apenas se aparecer
warning de reserved-memory.

## Baixa prioridade

- `SHA256SUMS-phase0.txt` não cobre `boot.img` nem `ramdisk.img`; o tar
  cobre o conjunto, mas o checksum individual não.
- `phase0-test.tar` não inclui `dts-patch/` nem `tools/`; é pacote de teste,
  não de rebuild.
- O README original referenciava `/tmp/opencode/evert-kernel` e
  `/tmp/opencode/evert-device`, que não existem no host de publicação.
- `CONFIG_DEVTMPFS` off: o mini-init cria `/dev/console`, `/dev/kmsg` e
  `/dev/null` com `mknod`; o stock 4.4 também tem DEVTMPFS off.
- `CONFIG_QCOM_TSENS` off, mas `CONFIG_THERMAL_TSENS=y` compila
  `msm-tsens.c`, que suporta `qcom,sdm630-tsens`. O sensor está coberto.
- `CONFIG_QCOM_LLCC` off: SDM630 não tem LLCC.
- `CONFIG_DEBUG_INFO_BTF` off: não é necessário para o boot; pode afetar
  bpfloader/netd no Android 15.
- `qcom,ipc-spinlock@1f40000` e `syscon@1f40000` mapeiam o mesmo bloco
  TCSR; baixo risco de sobreposição de providers.
- `rpm-glink` e o antigo `qcom,rpm-smd` compartilham IRQ 168; o glink
  registra a IRQ, o rpm-smd só usa para afinidade. Sem conflito.

## O que está certo

- Checksums dos 3 arquivos e do tar passam.
- Kernel embutido byte-idêntico a `kernel/out/arch/arm64/boot/Image`:
  40.843.272 bytes, versão
  `4.19.325-cip136-st20-perf-g6c095591a5c6`.
- 5 DTBs anexados, hashes idênticos a `dts-patch/evert*-4.19.dtb`; header
  v0, page 4096, load addresses e cmdline corretos.
- Board IDs e msm-ids dos 5 DTBs idênticos aos stock; o bootloader deve
  escolher o DTB certo.
- `patch_evert_rpm.py` reproduz os DTBs com diferenças apenas de numeração
  de phandle; sem drift semântico.
- RPM/GLINK/SMEM/TCSR/APCS/hwspinlock/reguladores/clocks habilitados; os
  phandles do DTB resolvem.
- `build2.log` limpo: 452 warnings, 0 erros. `build.log` é o build antigo
  que falhou em `walt.h`; não usar.
- `PSTORE_RAM/CONSOLE/PMSG` e ramoops com `reg`/tamanhos 32-bit corretos.
- `mini-init` cria nós estáticos, monta proc/sys, grava o marcador e
  reinicia em 8 s; o marcador deve aparecer no pstore mesmo sem UART.

## Recomendações antes de um próximo build

1. Habilitar `CONFIG_SERIAL_MSM=y` e `CONFIG_SERIAL_MSM_CONSOLE=y` e
   reempacotar as imagens.
2. Rebuildar `mini-init` com `MINI_INIT_BUILD_ID` e recriar a imagem mini.
3. Fazer backup real de `boot`/`vbmeta` antes de qualquer flash.
4. Manter o README com as ressalvas de console e de backup.
5. Testar primeiro a imagem mini; a patched só depois.
