# Esportes na Grande Vitória — passo a passo

Todo dia às 7h (horário de Brasília), o GitHub roda o `coletor.py`, que lê as
notícias das prefeituras, separa as de esporte e atualiza uma página que você
abre no navegador.

## O que você vai ter no final

Um endereço como `https://SEU-USUARIO.github.io/esportes-grande-vitoria/`
com as matérias novas no topo (marcadas como "novo"), o histórico dos últimos
dias e, no rodapé, a situação de cada site.

## Instalação (uns 10 minutos, sem terminal)

1. **Crie a conta** em https://github.com (gratuita).
2. **Crie o repositório:** botão **New** (ou o "+" no topo) → nome
   `esportes-grande-vitoria` → marque **Public** → **Create repository**.
3. **Suba os arquivos:** na página do repositório, clique em
   **uploading an existing file** e arraste para lá **o conteúdo da pasta**
   (`coletor.py`, `requirements.txt`, `LEIA-ME.md` e a pasta `.github`).
   Clique em **Commit changes**.
   - Se a pasta `.github` não subir arrastando (ela começa com ponto e alguns
     computadores a escondem), use **Add file → Create new file**, digite
     `.github/workflows/diario.yml` como nome e cole o conteúdo do arquivo.
4. **Rode a primeira vez:** aba **Actions** → "Coleta diária de notícias de
   esporte" → **Run workflow** → **Run workflow**. Espere ~1 minuto até
   aparecer o ✅ verde. (Se o GitHub pedir para habilitar os workflows,
   clique em **I understand my workflows, go ahead and enable them**.)
5. **Ligue a página:** **Settings → Pages** → em *Source* escolha
   **Deploy from a branch** → *Branch*: `main` e pasta `/docs` → **Save**.
   Em 1–2 minutos o endereço aparece no topo da tela.
6. Salve o endereço nos favoritos. Pronto: ele se atualiza sozinho todo dia.

## Se algo não funcionar

- **Actions deu ❌:** clique na execução, depois no passo que falhou, e me
  mande o texto do erro.
- **Um site aparece como "acesso negado" ou "erro" na página:** alguns sites
  proíbem leitura automática (robots.txt) ou bloqueiam robôs. O script respeita
  isso e não tenta contornar; use o link "abrir site" na própria página.
- **Um site aparece "atenção: nenhuma notícia reconhecida":** o layout dele é
  diferente do esperado. Me avise qual, que eu ajusto.

## Ajustes comuns (no arquivo `coletor.py`)

- **Horário:** em `.github/workflows/diario.yml`, linha `cron`. O horário é
  em UTC (Brasília = UTC−3). `"0 10 * * *"` = 7h.
- **Palavras de esporte:** lista `PALAVRAS_CHAVE`.
- **Endereço da página de notícias de uma prefeitura:** lista `CIDADES`.
