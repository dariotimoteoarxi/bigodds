# Bigodds no Google Cloud (máquina grátis e2-micro)

Tempo: cerca de 20 minutos. Só tu podes criar as contas; o resto está preparado nesta pasta.

## 1. Conta Google Cloud (5 min)
1. Abre https://console.cloud.google.com e entra com a tua conta Google.
2. Aceita os termos e carrega em **Iniciar avaliação gratuita**. Pedem um cartão **só para confirmar a identidade**: a avaliação dá 300 $ de crédito por 90 dias e não cobra nada sem autorização.
3. **Antes dos 90 dias**, em *Faturação*, carrega em **Ativar conta completa** (upgrade). Se não o fizeres, a máquina é desligada no fim da avaliação. A máquina e2-micro continua grátis depois do upgrade.
4. Proteção contra surpresas: *Faturação → Orçamentos e alertas → Criar orçamento* de **1 €**, com alertas a 50%, 90% e 100%.

## 2. Criar a máquina (5 min)
*Compute Engine → Instâncias de VM → Criar instância* (da primeira vez, ativa a API e espera 1 minuto):
- Nome: `bigodds`
- Região: **us-central1 (Iowa)**. Só us-central1, us-east1 e us-west1 são grátis. A distância não interessa para o Bigodds.
- Série **E2**, tipo de máquina **e2-micro**
- Disco de arranque: carrega em *Alterar*. Escolhe **Ubuntu 24.04 LTS (x86/64)**, tipo **Disco persistente padrão** (não "equilibrado") e **30 GB**.
- Firewall: deixa HTTP e HTTPS **desligados**. O acesso será privado, pelo Tailscale.
- **Criar**.

## 3. Instalar o Bigodds (5 min)
1. No teu PC, nesta pasta: `./empacotar.sh` (cria `bigodds.tar.gz` com a app, as tuas apostas e os modelos).
2. Na lista de VMs, carrega em **SSH** ao lado de `bigodds` (abre um terminal no browser).
3. No terminal SSH: menu **⚙ → Carregar ficheiro**. Envia `bigodds.tar.gz` e também `instalar.sh`.
4. Corre: `sudo bash instalar.sh`. No fim aparece "Bigodds a correr".

## 4. Abrir no telemóvel em qualquer lado (5 min, Tailscale grátis)
1. No terminal SSH: `sudo tailscale up`. Abre o link que aparece e entra com a tua conta Google (cria a conta Tailscale).
2. Na consola do Tailscale (https://login.tailscale.com/admin/dns), liga **MagicDNS** e **HTTPS Certificates**.
3. No terminal SSH: `sudo tailscale serve --bg 8765`. Aparece um endereço `https://bigodds.xxxx.ts.net`.
4. No telemóvel: instala a app **Tailscale**, entra com a mesma conta e abre esse endereço. No Chrome, usa *Adicionar ao ecrã principal*.

Os avisos ntfy continuam a funcionar sem nada disto. Ativa-os no Desempenho, na versão da nuvem.

## 5. Depois de mudar
- A partir de agora usa **só** a versão da nuvem, para as apostas ficarem num sítio só. No PC também a abres pelo endereço `https://bigodds.xxxx.ts.net` (instala o Tailscale no PC).
- Atualizações que eu fizer: `./empacotar.sh --codigo`. Envia o pacote pelo SSH e corre `sudo bash instalar.sh` (não mexe nas tuas apostas e faz cópia de segurança).

## 6. Confirmar que custa 0 € (daqui a 2–3 dias)
*Faturação → Relatórios*, agrupado por **SKU**. A máquina e o disco devem aparecer como gratuitos.
**Atenção:** o endereço IP público pode ser cobrado (cerca de 3–4 $ por mês, segundo fontes não oficiais; a página oficial do plano grátis não fala nisso). Se aparecer uma linha "External IP" com custo, diz-me: passamos para um aparelho em casa ou para outra solução.
