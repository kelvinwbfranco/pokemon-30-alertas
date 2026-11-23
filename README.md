# Pokémon 30 anos — alertas no Telegram

Projeto gratuito e experimental para **procurar** ofertas da coleção brasileira Pokémon TCG Celebração de 30 Anos. A rotina do GitHub Actions está agendada de 5 em 5 minutos, mas o GitHub pode atrasar ou não executar alguns agendamentos. O scraping de lojas pode ser bloqueado: **não há garantia de cobertura nem de que todos os produtos sejam examinados a cada 5 minutos**.

## O que já faz

- Limites pessoais: **ETB < R$ 470, fichário < R$ 230, pôster < R$ 110, miniatura Mew < R$ 250, miniatura Mewtwo < R$ 250 e Ditto Premium < R$ 340**. Outros produtos têm valores de referência no `config/products.json`.
- Seleciona uma loja por rodada entre Mercado Livre, Amazon Brasil, Magalu, Toy Mania e Ri Happy. A **busca de uma loja** acontece aproximadamente a cada 25 minutos; os links individuais em `watched_product_urls` são rechecados a cada execução.
- Só aceita anúncios com evidência de produto exato (nome da edição 30 anos, categoria e preço no JSON-LD da página), disponibilidade explícita e vendedor aprovado. **Marketplaces exigem vendedor identificado na página e presente em `trusted_marketplace_sellers`**, para evitar ofertas duvidosas.
- Envia mensagem ao Telegram se o preço **anunciado** estiver estritamente abaixo do limite e não repetir oferta igual/mais cara, usando `state.json` para lembrar o último melhor preço enviado.
- Não envia mensagem quando bot e chat ainda não estão configurados.

## Limitações importantes

**Não é um comparador de checkout.** Este protótipo não valida automaticamente cupons, frete, preço de Pix, estoque real ou reputação de todos os vendedores. Só considera dados estruturados explicitamente expostos em páginas públicas de produtos; páginas com proteção anti-bot, preços renderizados por JavaScript ou sem metadados suficientes são ignoradas. Sites podem alterar HTML, apresentar anúncios patrocinados ou bloquear requisições. O fato de a rotina executar não significa que verificou todas as lojas. **O desconto de cupons precisa ser checado manualmente antes da compra**. Nunca registre tokens no código, arquivos públicos nem nos logs.

## Configurar bot do Telegram

1. No Telegram, fale com [@BotFather](https://t.me/BotFather), envie `/newbot` e crie o bot. **Não envie o token em chats nem adicione ao repositório**.
2. Abra o seu bot e envie `/start`.
3. Descubra o seu ID numérico de usuário no Telegram (para uma conversa privada, normalmente coincide com o chat ID do bot). Você pode obter o ID pelas informações da conta em um bot confiável ou pelo método `getUpdates` da Telegram Bot API em ambiente privado. Não compartilhe o token.
4. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Crie `TELEGRAM_BOT_TOKEN` com o token e `TELEGRAM_CHAT_ID` com o número. O nome deve estar exatamente assim.
5. Vá à aba **Actions → Monitor Pokémon 30 anos → Run workflow**. Selecione `test_telegram = true` e confirme. Se o job finalizar com sucesso, deverá chegar a mensagem de teste no Telegram.
6. Depois rode novamente sem teste e consulte os logs. Se nenhum produto for detectado, veja o motivo nos logs e adicione links individuais em `config/products.json` → `watched_product_urls`: `[ {"url": "https://..."} ]` (somente nas lojas configuradas).

## Limites e manutenção

O GitHub Actions é gratuito para workflows em repositórios públicos nas condições atuais da plataforma, mas pode desativar o agendamento de um repositório público após 60 dias sem atividade. Os sites consultados podem bloquear automações. Para ampliar a cobertura, o ideal é usar APIs oficiais ou fontes autorizadas e testes de integração próprios para cada loja. Evite depender exclusivamente deste monitor para ofertas-relâmpago.

## Arquivos

- `.github/workflows/monitor.yml` — agendamento e envio de avisos
- `monitor.py` — identificação de produtos/preços e envio seguro ao Telegram
- `config/products.json` — lojas, limites e links acompanhados
- `state.json` — controle dos alertas já enviados (sem tokens)

## Teste local (opcional)

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python monitor.py
```
