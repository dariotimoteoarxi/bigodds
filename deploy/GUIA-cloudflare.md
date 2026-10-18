# Bigodds online: Cloudflare + GitHub (grátis, sem cartão)

**Como fica:**
- A app e as tuas apostas vivem na Cloudflare.
- O GitHub corre a análise de 30 em 30 min e, à hora dos jogos, os avisos de 5 em 5 min.
- O teu PC pode ficar desligado.
- Tempo: cerca de 25 minutos. Só tu podes criar as contas; o resto está preparado.

## 1. Cloudflare (5 min)
1. Cria a conta em https://dash.cloudflare.com/sign-up (email e palavra-passe, sem cartão).
2. Copia o **Account ID**: no painel, *Workers & Pages*, aparece à direita. Guarda-o.
3. Cria o **token**: *My Profile → API Tokens → Create Token → Create Custom Token*.
   - Nome: `bigodds-github`
   - Permissões:
     - Account → **Cloudflare Pages** → Edit
     - Account → **D1** → Edit
     - Account → **Workers KV Storage** → Edit
     - Account → **Account Settings** → Read
     - User → **User Details** → Read
   - *Account Resources*: a tua conta → *Continue → Create Token*.
   - **Copia o token já**: só aparece uma vez.

## 2. GitHub (5 min)
1. Cria a conta em https://github.com/signup (sem cartão).
2. No terminal do PC, instala a ferramenta do GitHub e liga-a à tua conta (abre o browser para confirmares; `workflow` deixa enviar as tarefas automáticas):
   ```bash
   sudo apt install gh
   ```
   ```bash
   gh auth login --web --scopes workflow
   ```

## 3. Criar o repositório e os segredos (5 min)
Na pasta do Bigodds:
```bash
cd ~/Secretária/domótica/consultor-apostas
```
```bash
gh repo create bigodds --public
```
O repositório é **público** porque assim o GitHub Actions não tem limite de minutos. O código fica visível, mas **as tuas apostas não**: estão só na Cloudflare, protegidas pela palavra-passe.

Os três segredos (cada comando pede o valor, que não aparece no ecrã):
```bash
gh secret set CLOUDFLARE_API_TOKEN -R "$(gh api user -q .login)/bigodds"
```
```bash
gh secret set CLOUDFLARE_ACCOUNT_ID -R "$(gh api user -q .login)/bigodds"
```
```bash
gh secret set BIGODDS_PALAVRA_PASSE -R "$(gh api user -q .login)/bigodds"
```
A palavra-passe é a que vais escrever na app. Usa uma longa.

## 4. Enviar o código (2 min)
```bash
git remote add origin "https://github.com/$(gh api user -q .login)/bigodds.git" && gh auth setup-git && git push -u origin main
```
O envio arranca sozinho a tarefa **Publicar**. Ela cria a base de dados, o espaço KV e a app. No GitHub, abre *Actions → Publicar*; no fim aparece o endereço, algo como `https://bigodds.pages.dev`.

## 5. Levar as tuas apostas do PC para a Cloudflare (2 min, uma vez)
```bash
export CLOUDFLARE_API_TOKEN='o-teu-token' CLOUDFLARE_ACCOUNT_ID='o-teu-account-id'
```
```bash
python3 cloud/migrar.py
```

## 6. Primeira análise
Abre *Actions → Bigodds → Run workflow* (modo `completo`), ou espera até 30 minutos.

## 7. Usar
- Abre o endereço da Cloudflare no telemóvel e escreve a palavra-passe (só uma vez por aparelho). No Chrome, usa *Adicionar ao ecrã principal*.
- Na **roda dentada**, ativa os *Avisos no telemóvel* (app ntfy).
- A partir daqui usa **só** o endereço da Cloudflare. A versão do PC deixa de receber as apostas novas.

## O que muda em relação ao PC
- **Placar com a app aberta:** ao minuto, como hoje (vem direto da ESPN).
- **Avisos com a app fechada (golos, cartões, cantos, intervalo, onzes, lembretes):** podem chegar até ~5–15 min depois. O GitHub corre as tarefas de 5 em 5 min e às vezes atrasa.
- **Análise e boletim do dia:** atualizam de 30 em 30 min.
- **Atualizações que eu fizer:** basta `git push`. A tarefa Publicar volta a pôr a app online sozinha.

## Se algo falhar
- *Actions* mostra cada tarefa a vermelho ou verde. Diz-me qual falhou e copio o erro daí.
- O GitHub desliga tarefas agendadas de repositórios parados 60 dias. Há uma tarefa mensal que evita isso.
