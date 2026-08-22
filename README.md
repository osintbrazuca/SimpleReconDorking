<h1 align="center">(SRDorking) - Simple Recon - Dorking v1.0.0</h1>

<p align="center">
  Ferramenta de dorking em múltiplos motores de busca para coleta de URLs em operações de OSINT e reconhecimento.
</p>

<h1 align="center">
  <a href="#"><img src="./assets/img/banner.png"width="700px" alt="Simple Recon URL"></a>
</h1>

<p align="center">
<a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/Python-3.10+-1E88E5?style=for-the-badge&logo=python&logoColor=white"></a>
<a href="#"><img alt="Versão" src="https://img.shields.io/badge/Versão-1.0.0-2E7D32?style=for-the-badge&logo=semanticrelease&logoColor=white"></a>
<a href="#"><img alt="Linux" src="https://img.shields.io/badge/Linux-suportado-EF6C00?style=for-the-badge&logo=linux&logoColor=white"></a>
<a href="#"><img alt="macOS" src="https://img.shields.io/badge/macOS-suportado-00838F?style=for-the-badge&logo=apple&logoColor=white"></a>
</p>

<p align="center">
<a href="https://github.com/osintbrazuca/SimpleReconDorking/blob/master/LICENSE"><img alt="Licença" src="https://img.shields.io/github/license/osintbrazuca/SimpleReconDorking?style=for-the-badge&color=1E88E5&logo=opensourceinitiative&logoColor=white"></a>
<a href="https://github.com/osintbrazuca/SimpleReconDorking/graphs/contributors"><img alt="Contribuidores" src="https://img.shields.io/github/contributors-anon/osintbrazuca/SimpleReconDorking?style=for-the-badge&color=2E7D32&logo=github&logoColor=white"></a>
<a href="https://github.com/osintbrazuca/SimpleReconDorking/issues"><img alt="Issues abertas" src="https://img.shields.io/github/issues-raw/osintbrazuca/SimpleReconDorking?style=for-the-badge&color=EF6C00&logo=github&logoColor=white"></a>
<a href="https://github.com/osintbrazuca/SimpleReconDorking/stargazers"><img alt="Estrelas" src="https://img.shields.io/github/stars/osintbrazuca/SimpleReconDorking?style=for-the-badge&color=F9A825&logo=github&logoColor=white"></a>
</p>

Ferramenta de **dorking** que utiliza multiplos motores de busca para coleta de URLs. O operador informa uma ou mais *dorks* - a partir de uma string livre (`-d`, `--dork`), um arquivo (`-D`, `--dork-file`), do catálogo embutido por categoria (`--dork-category`) ou via stdin - e a ferramenta roda cada dork contra várias fontes de busca em paralelo, devolvendo a união das URLs encontradas. Diferente do resto da família SimpleRecon, **não há crawler, não há host semente**: a única fonte de dados são os índices das fontes de busca.

> [!NOTE]
> Construída em Python assíncrono, sem lógica de resolução DNS e sem dependências de shell externas. Derivada do [SimpleReconURL](https://github.com/osintbrazuca/SimpleReconURL), reorientada de "uma URL semente" para "uma dork, muitas fontes".

```
Author:   Cleiton Pinheiro a.k.a MrCl0wn
Blog:     https://blog.mrcl0wn.com
GitHub:   https://github.com/MrCl0wnLab
Twitter:  https://twitter.com/MrCl0wnLab
```

---

> [!CAUTION]
> **Aviso legal:** usar o SimpleReconDorking para atacar alvos sem consentimento mútuo prévio é ilegal.
> É responsabilidade do usuário final obedecer a todas as leis municipais, estaduais e federais aplicáveis.
> Os desenvolvedores não assumem qualquer responsabilidade por mau uso ou dano causado por este programa.
> O catálogo de dorks embutido (`config/dork_categorys.json`) existe para **auditoria e descoberta de exposições em ativos
> sob sua responsabilidade** - não é uma lista de alvos.

## Índice

- [Instalação](#instalação)
- [Chaves de API](#chaves-de-api)
- [Uso](#uso)
- [Entrada de dorks](#entrada-de-dorks)
- [Catálogo embutido de dorks](#catálogo-embutido-de-dorks)
- [Fontes de busca](#fontes-de-busca)
- [Mojeek, Ecosia, Swisscows, So.com e Dogpile: bypass via navegador](#mojeek-ecosia-swisscows-socom-e-dogpile-bypass-via-navegador)
- [Perfis](#perfis)
- [Presets de execução](#presets-de-execução)
- [Filtros](#filtros)
- [Paginação e rate limiting](#paginação-e-rate-limiting)
- [Proxy](#proxy)
- [User-Agent](#user-agent)
- [Headers](#headers)
- [Mapa de dorks: grafo JSON e visualização HTML](#mapa-de-dorks-grafo-json-e-visualização-html)
- [Relatório Markdown](#relatório-markdown)
- [Banco de dados: persistência SQLite](#banco-de-dados-persistência-sqlite)
- [Monitoramento contínuo (--watch)](#monitoramento-contínuo---watch)
- [Formatos de saída](#formatos-de-saída)
- [Encadeando com outras ferramentas](#encadeando-com-outras-ferramentas)
- [Criando uma nova fonte](#criando-uma-nova-fonte)
- [Banners](#banners)
- [Todas as flags](#todas-as-flags)

---

## Instalação

```bash
git clone https://github.com/osintbrazuca/SimpleReconDorking
cd SimpleReconDorking
pip install -r requirements.txt
```

**Dependências** (`requirements.txt`):

| Pacote | Para que serve |
|---|---|
| `httpx[socks]` | Cliente HTTP assíncrono usado por todas as fontes (`[socks]` habilita proxy `socks5://` - veja [Proxy](#proxy)) |

Todo o resto (`sqlite3`, `asyncio`, `re`, `json`, ...) é biblioteca padrão do Python 3.10+.

### Docker

Roda sem precisar de Python instalado. Dois caminhos de build, mesma imagem, e os argumentos da CLI passam direto:

```bash
# A) a partir do código local (contexto de build = raiz do repositório)
docker build -t docker/simplerecondorking -f docker/Dockerfile .

# B) direto do GitHub, sem checkout local
docker build -t docker/simplerecondorking - < docker/Dockerfile.remote

# execução (o que vem depois do nome da imagem vai para o simplerecondorking.py)
docker run --rm docker/simplerecondorking -d 'site:target.com ext:sql'
```

Veja [docker/README.md](docker/README.md) para as opções completas de build, montagem das chaves de API, persistência de resultados (volume do `--db`) e registro do `--watch`.

---

## Chaves de API

> [!IMPORTANT]
> As chaves ficam em `config/api_keys.json`, que está no gitignore justamente para
> não ser commitado por acidente. Nunca versione esse arquivo preenchido.

```json
{
    "brave": "",
    "github_token": "",
    "intelx_key": "",
    "publicwww": ""
}
```

| Chave | Fonte | Onde conseguir |
|---|---|---|
| `brave` | `brave` | https://brave.com/search/api/ |
| `github_token` | `github` | https://github.com/settings/tokens (escopo `public_repo`) |
| `intelx_key` | `intelx` | https://intelx.io/account?tab=developer |
| `publicwww` | `publicwww` | https://publicwww.com/api.html (plano pago para `export=urls`) |

Toda fonte sem chave configurada retorna um conjunto vazio silenciosamente - nunca interrompe o restante da execução.

---

## Uso

```bash
# listar todos comandos
python simplerecondorking.py --help

# uma dork solta
python simplerecondorking.py -d 'site:target.com ext:sql'

# uma categoria inteira do catálogo embutido, com {TARGET} preenchido
python simplerecondorking.py -t target.com --dork-category files

# listar o que existe
python simplerecondorking.py --list-sources
python simplerecondorking.py --list-profiles
python simplerecondorking.py --list-category
python simplerecondorking.py --list-examples
```

<h1 align="center">
  <a href="#"><img src="./assets/img/menu.png" ></a>
</h1>

### Exemplos em contexto de OSINT

```bash
# auditar exposições comuns de um domínio próprio
python simplerecondorking.py -t meudominio.com \
  --dork-category files,config,git_exposure,backup -o json --outfile audit.json

# caçar menções de um domínio em pastes/código, sem operadores de busca
python simplerecondorking.py -d 'meudominio.com' --category code,leak

# combinar uma dork avulsa com uma categoria inteira, no mesmo run
python simplerecondorking.py -d 'intitle:"index of" site:{TARGET}' -t meudominio.com \
  --dork-category panels

# encadear com httpx para confirmar quais URLs ainda respondem
python simplerecondorking.py -t meudominio.com --dork-category files --no-banner | httpx -silent

# rodar atrás de um pool de proxies, trocando ao ser bloqueado
python simplerecondorking.py -t meudominio.com --dork-category files \
  --proxy-file proxies.txt --proxy-rotate round-robin --proxy-rotate-status 403,429
```

<h1 align="center">
  <a href="#"><img src="./assets/img/execute.png" ></a>
</h1>

---

## Entrada de dorks

Toda dork é um **template**: pode conter o placeholder `{TARGET}`, substituído pelo valor de `-t/--target`. Uma dork sem `{TARGET}` é enviada literalmente. Isso é útil para buscar uma assinatura na web inteira, sem alvo.

| Flag | O que faz |
|---|---|
| `-d, --dork QUERY` | Uma única dork |
| `-D, --dork-file FILE` | Arquivo com uma dork por linha (`#` comenta, linhas em branco ignoradas) |
| `--dork-category CAT[,CAT...]` | Uma ou mais categorias do catálogo embutido (`config/dork_categorys.json`) |
| `--stdin` | Lê dorks adicionais de stdin, uma por linha |
| `-t, --target TARGET` | Domínio, host, IP ou texto que substitui `{TARGET}` nas dorks selecionadas |

```bash
python simplerecondorking.py -d 'site:target.com ext:log' -v 1 --profile fast
```

As três primeiras fontes são **aditivas**: dá para combinar `-d` com `--dork-category` no mesmo comando. Uma dork que precisa de `{TARGET}` e não recebe `-t` é **pulada com aviso**, nunca enviada com um `{TARGET}` literal. Isso seria ruído puro em toda fonte.

```bash
echo 'site:target.com ext:log' | python simplerecondorking.py --stdin
cat mydorks.txt | python simplerecondorking.py --stdin -t target.com
```

---

## Catálogo embutido de dorks

O arquivo `config/dork_categorys.json` é a fonte única do catálogo embutido. A chave raiz `dorks` contém as categorias. Cada categoria possui:

| Campo | Tipo | Finalidade |
|---|---|---|
| `description` | string | Resumo exibido por `--list-category` |
| `operators` | lista de strings | Dorks com operadores como `site:`, `inurl:`, `intitle:` e `ext:` |
| `operators_out` | lista de strings | Versões equivalentes sem operadores de busca |

Estrutura mínima de uma categoria:

```json
{
  "dorks": {
    "api": {
      "description": "API surface and machine-readable specs on {TARGET}",
      "operators": [
        "site:{TARGET} inurl:swagger"
      ],
      "operators_out": [
        "{TARGET} \"swagger\""
      ]
    }
  }
}
```
<h1 align="center">
  <a href="#"><img src="./assets/img/categorias.png" ></a>
</h1>

Para adicionar uma categoria, inclua uma nova chave dentro de `dorks` e preencha as duas famílias. Não é necessário alterar código Python. JSON não aceita comentários nem vírgula depois do último item. Um arquivo ausente ou inválido resulta em um catálogo vazio.

| Categoria | Cobre |
|---|---|
| `files` | Listagens de diretório e arquivos soltos indexados |
| `config` | Arquivos de configuração/ambiente que vazam segredos (`.env`, `.ini`, `web.config`...) |
| `panels` | Painéis de admin, login e gerenciamento |
| `errors` | Erros de aplicação e stack traces expostos |
| `cloud` | Buckets S3/GCS/Azure Blob referenciando o alvo |
| `docs` | Documentos sensíveis indexados (PDF, XLS, DOC, SQL, backup) |
| `git_exposure` | `.git`, `.svn`, `.DS_Store`, manifestos de dependência expostos |
| `backup` | Arquivos e dumps de backup alcançáveis |
| `api` | Specs OpenAPI/Swagger, GraphQL, rotas `/api/` |
| `remote_access` | Painéis de VPN, RDP, Citrix, Jenkins, GitLab expostos |
| `cameras` | Interfaces de câmeras IP/webcam expostas |

### Seleção da família

O valor de `-t/--target` define qual lista da categoria será usada:

| Valor de `--target` | Família selecionada |
|---|---|
| Domínio ou host, como `example.com` ou `app.example.com` | `operators` |
| Endereço IPv4 ou IPv6 | `operators` |
| Texto livre, como `Acme Corporation` | `operators_out` |
| Não informado | As dorks com `{TARGET}` são ignoradas com aviso |

Essa seleção permite pesquisar organizações, produtos, pessoas e frases sem produzir um operador `site:` inválido. Fontes que não suportam operadores ainda aplicam `Dork.plain_terms()` quando recebem uma dork avulsa com operadores.

```bash
python simplerecondorking.py --list-category
python simplerecondorking.py -t target.com --dork-category files,config,backup
python simplerecondorking.py -t 'Acme Corporation' --dork-category api,docs
```

---

## Fontes de busca

```bash
python simplerecondorking.py --list-sources
```

Toda fonte recebe a mesma dork e devolve URLs; a diferença é o quanto cada uma entende de operadores de busca (`site:`, `ext:`, `inurl:`...). Fontes marcadas **free-text only** não entendem operadores - a dork é convertida automaticamente para termos soltos (`Dork.plain_terms()`) antes de ser enviada, e isso é registrado em `-v 1`.

### Web

| Fonte | Exige chave | Observações |
|---|---|---|
| `yahoo` | Não | Suporte completo a operadores; a fonte grande que ainda responde `site:` sem desafio |
| `bing` | Não | Suporte completo; **melhor esforço**, costuma servir desafio Cloudflare Turnstile |
| `google` | Não | Scraping de google.com/search: **melhor esforço**, geralmente bloqueado - use `googlecse` |
| `googlecse` | Não | Google via Custom Search Engines públicos: cobertura real do Google, sem chave |
| `duckduckgo` | Não | Endpoint lite (sem JS); **melhor esforço**, sensível a rate limit por IP |
| `startpage` | Não | Resultados do Google via proxy de privacidade; **melhor esforço**, scraping |
| `brave` | Sim | API oficial da Brave Search, suporte completo a operadores |
| `marginalia` | Não | Índice independente e não comercial; **free-text only** |
| `searx` | Não | Metabusca federada via instâncias públicas SearXNG (JSON API); disponibilidade variável |
| `seznam` | Não | Seznam.cz - fonte dominante na República Tcheca, índice próprio, paginação confirmada |
| `naver` | Não | Naver - fonte dominante na Coreia do Sul (~55-60% do mercado), índice próprio, página única |
| `daum` | Não | Daum (Kakao) - 2ª fonte coreana, índice próprio, página única |
| `yahoojp` | Não | Yahoo Japan - operação independente (LY Corporation), mesma base do Yahoo global, paginação confirmada |
| `yandex` | Não | Yandex - índice próprio, operadores exclusivos (`host:`, `rhost:`, `date:` por faixa); **melhor esforço** |
| `baidu` | Não | Baidu - maior fonte chinesa; **melhor esforço**, geralmente serve verificação anti-bot |
| `mojeek` | Não | Mojeek - índice próprio; **precisa de navegador** (`requirements-browser.txt`), veja abaixo |
| `ecosia` | Não | Ecosia - índice em parceria com a Qwant; **precisa de navegador**, Cloudflare Turnstile (depende muito de reputação de IP) |
| `swisscows` | Não | Swisscows - índice suíço, foco em privacidade; **precisa de navegador** (SPA renderizado via JS, sem desafio) |
| `so` | Não | So.com (360 Search) - fonte chinesa (Qihoo 360); **precisa de navegador**, pagina clicando no botão real "próxima página" |
| `dogpile` | Não | Dogpile - metabusca (Infospace/System1); **precisa de navegador**, **free-text only** (operadores disparam um bloqueio WAF), **melhor esforço** (IP é rate-limitado rápido) |
| `aol` | Não | AOL Search - portal que redireciona para o backend do Yahoo (YHS); suporte completo a operadores, sem navegador |

> [!NOTE]
> `seznam`, `naver`, `daum` e `yahoojp` foram validados ao vivo (2026-08): devolvem links de resultado reais direto no HTML estático, sem exigir JavaScript. `aol` também: sua busca redireciona para o backend do Yahoo (YHS, "Yahoo Hosted Search"), então herda o mesmo mecanismo de link direto sem navegador. Várias outras fontes pesquisadas nessa rodada - Qwant, MetaGer, Sogou, Ask.com, Lycos, You.com, WebCrawler - foram **descartados do catálogo** após teste ao vivo via HTTP puro; nenhum foi testado via navegador (ao contrário de `mojeek`/`ecosia`/`swisscows`/`so`/`dogpile` abaixo), então um deles pode muito bem se comportar como `dogpile` se alguém quiser investigar. `mojeek`, `ecosia`, `swisscows`, `so` e `dogpile` também bloqueavam via HTTP puro, mas por motivos que um navegador headless resolve - em vez de descartar, foram implementados com Playwright (veja [Mojeek, Ecosia, Swisscows, So.com e Dogpile: bypass via navegador](#mojeek-ecosia-swisscows-socom-e-dogpile-bypass-via-navegador)).

<h1 align="center">
  <a href="#"><img src="./assets/img/sources.png" ></a>
</h1>

### Código

| Fonte | Exige chave | Observações |
|---|---|---|
| `grep_app` | Não | Busca de código no grep.app; **free-text only**, rate limit agressivo (429) |
| `github` | Sim | Busca de código no GitHub; **free-text only**, a melhor fonte para rotas de API |

### Código-fonte

| Fonte | Exige chave | Observações |
|---|---|---|
| `publicwww` | Sim | Busca no HTML/JS/CSS das páginas, não no texto; **free-text only** |

### Jurídico

| Fonte | Exige chave | Observações |
|---|---|---|
| `jusbrasil` | Não | JusBrasil - consulta processual pública (nome/CPF/CNPJ/nº de processo); **free-text only**, **melhor esforço** (desafio Cloudflare) |

### Vazamentos

| Fonte | Exige chave | Observações |
|---|---|---|
| `intelx` | Sim | Seletores de URL do phonebook do Intelligence X: vazamentos, pastes, dumps; **free-text only** |

---

## Mojeek, Ecosia, Swisscows, So.com e Dogpile: bypass via navegador

Cinco fontes só funcionam de verdade com um navegador de verdade por trás - uma requisição HTTP simples nunca chega ao resultado. Cada uma bloqueia por um motivo diferente:

| Fonte | Por que HTTP puro falha | Como é resolvido |
|---|---|---|
| `mojeek` | Checkbox ALTCHA (prova de trabalho client-side) | Clique forçado no checkbox + espera pela verificação; token `chv` reaproveitado nas páginas seguintes |
| `ecosia` | Cloudflare Turnstile (avaliação comportamental/fingerprint) | Espera passiva o desafio resolver sozinho (sem clique), com fallback de clique se um checkbox aparecer |
| `swisscows` | Sem desafio nenhum - é só um SPA renderizado inteiramente via JavaScript | Carrega a página e espera o JS renderizar; sem clique nem verificação |
| `so` | SPA renderizado via JS **e** URL real do resultado escondida num atributo `data-mdurl`, não no `href` visível (que é um wrapper de redirecionamento `so.com/link?m=...`) | Renderiza a página e lê `data-mdurl`; pagina clicando no botão real "próxima página" (`#snext`) em vez de montar a URL com o `psid` na mão - esse token é gerado por sessão e uma URL construída manualmente não é garantia de funcionar |
| `dogpile` | Bloqueio direto (403) via requisição HTTP simples; **e** um WAF da CloudFront bloqueia especificamente `site:`/`filetype:`/`inurl:` na query (confirmado: dois-pontos em termo qualquer passa, esses operadores especificamente não) | Renderiza via navegador (passa limpo, HTTP 202); toda dork é rebaixada para termos livres antes de ser enviada - aqui isso não é só "melhor cobertura", é a diferença entre funcionar e ser bloqueado |

```bash
# preparação única (dependência opcional, download do navegador ~150MB)
pip install -r requirements-browser.txt
playwright install chromium

python simplerecondorking.py -d 'site:target.com' --sources mojeek
python simplerecondorking.py -d 'site:target.com' --sources ecosia
python simplerecondorking.py -d 'site:target.com' --sources swisscows
python simplerecondorking.py -d 'site:target.com' --sources so
python simplerecondorking.py -d 'target.com' --sources dogpile
python simplerecondorking.py -d 'target.com' --profile browser --pages 3
```

> [!NOTE]
> Sem o Playwright instalado, as cinco fontes se autodesabilitam com uma única mensagem em `-v 1` e o restante da ferramenta funciona normalmente - mesmo contrato do `browser` do SimpleReconURL. `mojeek`, `ecosia` e `dogpile` são **melhor esforço**, em graus diferentes: `mojeek` e `dogpile` bloqueiam por reputação de IP num nível "tudo ou nada" (403 direto quando bloqueado - no caso do `dogpile`, algumas requisições seguidas da mesma máquina já bastam para disparar); `ecosia` depende muito mais de reputação de IP/rede porque o Cloudflare Turnstile avalia sinais de automação do navegador além do IP - um Chromium headless rodando de um IP de datacenter tende a nunca passar, mesmo com técnicas comuns de stealth (testado), mas resolve automaticamente numa sessão de navegador real, sem interação nenhuma, segundo relato direto do operador. `swisscows` e `so` não têm esse problema - validados ao vivo com resultados reais e paginação funcionando de forma consistente (`so` precisou trocar a condição de espera de `load` para `domcontentloaded`: a página é pesada o bastante para o evento `load` travar sem necessidade).

---

## Perfis

Grupos de fontes prontas, definidos em `config/profiles.json`.

```bash
python simplerecondorking.py --list-profiles
```

| Perfil | Fontes |
|---|---|
| `fast` | `googlecse`, `yahoo`, `duckduckgo`, `seznam`, `aol` - keyless e respondem de forma confiável |
| `web` | Toda fonte de busca web geral (inclui as de melhor esforço) |
| `keyless` | Toda fonte que não exige chave |
| `code` | `grep_app`, `github` |
| `intel` | `publicwww`, `intelx` (ambos exigem chave) |
| `browser` | `mojeek`, `ecosia`, `swisscows`, `so`, `dogpile` - precisam de `requirements-browser.txt` |
| `full` | Toda fonte registrada |

```bash
python simplerecondorking.py -d 'site:target.com ext:sql' --profile fast
```

`--profile` tem precedência sobre `--sources`/`--category`. `--exclude` é aplicado depois de qualquer seleção, incluindo perfis.


<h1 align="center">
  <a href="#"><img src="./assets/img/profiles.png" ></a>
</h1>

---

## Presets de execução

Como no resto da família SimpleRecon, `--config FILE` carrega um JSON com valores default para as flags - só é aplicado onde a flag ainda está no default do argparse, então flags explícitas na linha de comando sempre vencem.

```bash
cp config/run_config.example.json myrun.json
# edite myrun.json com suas preferências
python simplerecondorking.py -t target.com --dork-category files --config myrun.json
```

Todas as flags de proxy são chaves válidas do preset (`proxy`, `proxy_file`, `proxy_source`, `proxy_profile`, `proxy_rotate`, `proxy_rotate_secs`, `proxy_rotate_reqs`, `proxy_rotate_status`, `proxy_rotate_body`, `proxy_rotate_regex`, `proxy_retries`, `proxy_ban_after`, `proxy_fallback_direct`) - o que importa, porque uma linha de comando com pool e rotação fica impronunciável. O mesmo vale para `user_agent`/`ua_file`/`ua_source`/`ua_profile` e `header`/`header_file`/`header_source`/`header_profile`, e para o bloco `options` de um perfil em `config/profiles.json`.

```json
{
  "proxy_file": "proxies.txt",
  "proxy_rotate": "round-robin",
  "proxy_rotate_status": "403,429",
  "proxy_ban_after": 2
}
```

> [!NOTE]
> `proxy` aceita tanto uma string (`"http://a:8080"`) quanto uma lista (`["http://a:8080", "http://b:8080"]`) - presets escritos antes de `--proxy` virar repetível continuam funcionando.

---

## Filtros

Por padrão, **nada é filtrado**: uma dork como `"target.com" site:pastebin.com` deve mesmo devolver URLs em `pastebin.com` - é o que foi pedido. Os quatro filtros abaixo são opt-in e combinam entre si como **AND** (uma URL só sobrevive se passar em todos os filtros ativos); dentro de `--filter-string` (várias strings separadas por vírgula) o critério é **OR** - basta casar uma. O que qualquer filtro rejeita não é descartado: vai para `extras` (visível em `-v 3` e persistido no `--db`).

| Flag | Mantém a URL se... |
|---|---|
| `--filter-host HOST` | está em `HOST` ou um subdomínio dele |
| `--filter-string LIST` | contém qualquer uma destas strings (case-insensitive) |
| `--filter-regex PATTERN` | casa com este regex (um padrão só - use `\|` para alternativas, já que vírgula é sintaxe comum de regex) |
| `--filter-file FILE` | contém qualquer string do arquivo (um termo por linha; soma ao `--filter-string`) |

```bash
# sem filtro: mantém tudo que a fonte devolveu
python simplerecondorking.py -d '"target.com" site:pastebin.com' -t target.com

# com --filter-host: hits fora do host vão para extras
python simplerecondorking.py -t target.com --dork-category files --filter-host target.com -v 3

python simplerecondorking.py -t target.com --dork-category files --filter-string ".pdf,.doc,.xls"
python simplerecondorking.py -t target.com --dork-category files --filter-regex '\.(sql|env)$'
python simplerecondorking.py -t target.com --dork-category files --filter-file keywords.txt
```

---

## Paginação e rate limiting

`--pages N` (padrão 2, teto 20) controla quantas páginas de resultado cada par (fonte, dork) percorre. Toda fonte paginada ainda aplica seu próprio teto interno - uma cota de API gratuita ou um limiar de anti-bot é quase sempre mais restritivo do que o pedido aqui. `--rate-limit N` limita requisições concorrentes por fonte; `--threads N` é o portão de concorrência para os pares (fonte, dork) em voo.

```bash
python simplerecondorking.py -t target.com --dork-category files --pages 5
python simplerecondorking.py -d 'site:target.com' --rate-limit 2 --timeout 15
```

---

## Proxy

`--proxy URL` é **repetível** e `--proxy-file FILE` soma um arquivo por cima, então o pool se monta de qualquer uma das duas formas (ou das duas juntas). Credenciais podem vir embutidas (`http://user:senha@host:porta`) - elas nunca aparecem nos logs, que mostram `http://***@host:porta`.

```bash
python simplerecondorking.py -d 'site:target.com' --proxy socks5://127.0.0.1:9050
python simplerecondorking.py -d 'site:target.com' --proxy http://a:8080 --proxy http://b:8080
python simplerecondorking.py -t target.com --dork-category files --proxy-file proxies.txt
```

### Direcionamento

`--proxy-source` e `--proxy-profile` decidem **quem** usa o pool - combinam entre si como AND:

| Flag | Restringe o pool a... |
|---|---|
| `--proxy-source LIST` | só estas fontes (nomes separados por vírgula); sem a flag, todas usam o pool |
| `--proxy-profile LIST` | execuções onde o `--profile` ativo está nesta lista; sem `--profile` na linha de comando, a guarda nunca abre e o pool fica configurado mas sem uso |

```bash
# só mojeek e dogpile (as duas fontes mais sujeitas a bloqueio de IP) usam o proxy
python simplerecondorking.py -t target.com --sources mojeek,dogpile \
  --proxy http://a:8080 --proxy-source mojeek,dogpile

# o proxy só vale quando --profile browser está ativo nesta execução
python simplerecondorking.py -t target.com --profile browser \
  --proxy http://a:8080 --proxy-profile browser
```

### Rotação

| Flag | Efeito |
|---|---|
| `--proxy-rotate MODE` | `sticky` (padrão) usa um até falhar; `round-robin` percorre o pool; `random` sorteia por requisição |
| `--proxy-rotate-secs N` | Troca depois de N segundos no mesmo proxy |
| `--proxy-rotate-reqs N` | Troca depois de N requisições no mesmo proxy |
| `--proxy-rotate-status L` | Troca ao receber estes códigos (`403,429,503`) |
| `--proxy-rotate-body L` | Troca ao casar estas strings no corpo (case-insensitive) |
| `--proxy-rotate-regex PATTERN` | Troca ao casar este regex no corpo (um padrão só, mesma razão do `--filter-regex`) |
| `--proxy-retries N` | Trocas por requisição antes de desistir (padrão 2) |
| `--proxy-ban-after N` | Tira do pool após N falhas seguidas (padrão 3); um sucesso zera a contagem |
| `--proxy-fallback-direct` | Permite sair direto quando o pool esgota |

Os gatilhos são **cumulativos** - `--proxy-rotate round-robin --proxy-rotate-status 429` é combinação válida. Falha de conexão (proxy morto) conta como gatilho por si só, senão o modo de falha mais comum nunca seria detectado.

```bash
python simplerecondorking.py -t target.com --dork-category files \
  --proxy-file proxies.txt --proxy-rotate round-robin \
  --proxy-rotate-status 403,429 --proxy-ban-after 2
```

> [!IMPORTANT]
> Quando **todo** o pool é banido, a execução **aborta com exit 2** em vez de continuar. Sair direto nesse momento vazaria o IP real justamente quando o operador acreditava estar protegido - por isso é preciso pedir explicitamente com `--proxy-fallback-direct`.

### Duas assimetrias que valem conhecer

**Fontes de navegador não rotacionam no meio.** O Playwright fixa o proxy no launch, então `mojeek`, `ecosia`, `swisscows`, `so` e `dogpile` recebem **um proxy por fetch**. Não é só custo: o `psid` do `so` e o token `chv` do `mojeek` estão ligados ao IP que os obteve, então trocar no meio corromperia o resultado. Consequência contra-intuitiva: `--proxy-rotate-status 403` **não resgata** o `dogpile`, que é justo quem mais devolve 403. O que essas cinco fazem é reportar o bloqueio ao pool, então o `--proxy-ban-after` retira o proxy queimado para as tarefas seguintes.

**Duas fontes fixam um proxy por fetch de propósito.** `googlecse` busca o `cse_token` num IP e o gasta na chamada seguinte - trocar no meio produziria o 403 que se queria evitar. `intelx` abre um job de busca cobrado no servidor, e repetir a requisição cobraria a cota duas vezes. Ambas usam proxy normalmente, só não rotacionam dentro da mesma execução.

---

## User-Agent

`--ua` é um alias curto de `--user-agent` (mesmo destino, os dois funcionam). Por padrão, sem nenhuma das duas, cada requisição sorteia um User-Agent de navegador real de `assets/txt/user_agents.txt` - o UA literal do projeto (`SimpleReconDorking/1`) recebe bloqueio instantâneo em quase toda fonte.

```bash
python simplerecondorking.py -d 'site:target.com' --ua "Mozilla/5.0 (compatível)"
```

### `--ua-file`: um pool em vez de um valor só

`--ua-file FILE` lê um User-Agent por linha; com mais de um, **um é sorteado por tarefa (fonte, dork)** - não por requisição dentro da mesma tarefa. Se `--ua-file` e `--ua`/`--user-agent` forem passados juntos, o arquivo vence.

```bash
python simplerecondorking.py -t target.com --dork-category files --ua-file meus_uas.txt
```

### Direcionamento

`--ua-source`/`--ua-profile` restringem **quem** recebe o UA customizado (arquivo ou valor único) - mesmo par AND de `--proxy-source`/`--proxy-profile`. Fora do direcionamento, a fonte volta ao sorteio automático de sempre.

```bash
# só mojeek recebe o UA customizado; as demais sorteiam normalmente
python simplerecondorking.py -t target.com --sources mojeek,yahoo \
  --ua "Mozilla/5.0 (Android 14; Mobile)" --ua-source mojeek
```

---

## Headers

`--header 'JSON'` manda cabeçalhos HTTP extras como um objeto JSON - nome e valor como string:

```bash
python simplerecondorking.py -d 'site:target.com' \
  --header '{"user-agent": "android", "Cookie": "guest_id_marketing=v1%3A1787"}'
```

`--header-file FILE` lê o mesmo formato de um arquivo; se os dois forem passados juntos, mesclam por chave e `--header` vence em colisão. Os headers extras são mesclados **por último**, depois de qualquer coisa que a própria fonte já monte (inclusive o resultado de `browser_headers()`/`--ua-file`) - por isso `--header` consegue sobrescrever até o User-Agent, não importa a caixa (`user-agent` sobrepõe `User-Agent` normalmente).

```bash
python simplerecondorking.py -d 'site:target.com' --header-file headers.json
```

### Direcionamento

`--header-source`/`--header-profile`, mesmo par AND das demais famílias de direcionamento (proxy, UA). Fora do direcionamento, a fonte não recebe headers extras nenhum.

```bash
python simplerecondorking.py -t target.com --sources aol,yahoo \
  --header '{"X-Custom": "1"}' --header-source aol
```

> [!NOTE]
> Nas 5 fontes de navegador (`mojeek`, `ecosia`, `swisscows`, `so`, `dogpile`), os headers extras vão para o `extra_http_headers` do Playwright. Se `--header` também setar `user-agent`, o cabeçalho HTTP enviado reflete o valor do `--header`, mas o `navigator.userAgent` visível para o JavaScript da página continua o do `--ua`/`--ua-file` (ou o sorteado automaticamente) - o Playwright não sincroniza os dois. Combinar os dois de propósito para forjar UAs diferentes por camada não foi testado contra um anti-bot de verdade.

---

## Mapa de dorks: grafo JSON e visualização HTML

`--network-map` inclui um grafo `nodes`/`edges` no JSON: uma estrela de três níveis **alvo → dork → URL**, mais uma aresta direta alvo → filtrado para URLs excluídas por um `--filter-*` ativo. `--network-html FILE` escreve uma página HTML autocontida com [vis-network](https://visjs.github.io/vis-network/) para explorar o grafo interativamente, junto com qualquer `-o` escolhido.

```bash
python simplerecondorking.py -t target.com --dork-category files --network-html map.html
python simplerecondorking.py -t target.com --dork-category files -o json --network-map --outfile out.json
```

---

## Relatório Markdown

`-o markdown` gera um relatório com resumo, lista completa de URLs, extras e contribuição por fonte e por dork.

```bash
python simplerecondorking.py -t target.com --dork-category files -o markdown --outfile report.md
```

---

## Banco de dados: persistência SQLite

Um `--db FILE` funciona como armazenamento **e** fonte de comparação. Sem `--db-news`, salva a execução inteira (URLs, e em `-v 3` também as URLs externas). Com `--db-news`, compara contra tudo que já foi salvo para aquele `-t/--target` e imprime + salva só o que é novo.

```bash
python simplerecondorking.py -t target.com --dork-category files --db recon.db
python simplerecondorking.py -t target.com --dork-category files --db recon.db --db-news

# inspecionar
python simplerecondorking.py --db recon.db --db-list urls
python simplerecondorking.py --db recon.db --db-list extras
python simplerecondorking.py --db-list history   # log de comandos, config/system.db fixo
```

### Esquema

```sql
CREATE TABLE urls (
    id, seed, url, source, dork, first_seen
);
CREATE TABLE extras (
    id, seed, type, value, first_seen
);
```

`config/system.db` é um banco **separado e fixo** (log de comandos + jobs do `--watch`), nunca passado por `--db`.

---

## Monitoramento contínuo (--watch)

```bash
# registra o comando atual num agendamento cron (armazenado em config/system.db)
python simplerecondorking.py -t target.com --dork-category files --db target.db --quiet \
  --watch-add "0,15,30,45 * * * *"

# roda o agendador (jobs vencidos no mesmo minuto rodam em paralelo)
python simplerecondorking.py --watch

# gerencia os jobs
python simplerecondorking.py --watch-list
python simplerecondorking.py --watch-del 3
python simplerecondorking.py --watch-clear
```

---

## Formatos de saída

`-o {txt,json,csv,ndjson,html,markdown}` (padrão `txt`). `ndjson` é uma linha JSON por URL - ideal para pipes; `html` é o mapa interativo; `markdown` é o relatório humano.

```bash
python simplerecondorking.py -t target.com --dork-category files -o json --outfile result.json
python simplerecondorking.py -d 'site:target.com' --no-banner > urls.txt
```

---

## Encadeando com outras ferramentas

```bash
# probing HTTP
python simplerecondorking.py -t target.com --dork-category files --no-banner | httpx -silent

# scanner de vulnerabilidades
python simplerecondorking.py -t target.com --dork-category files --no-banner | httpx -silent | nuclei -t exposures/ -silent

# string-x (strx) - github.com/MrCl0wnLab/string-x
python simplerecondorking.py -t target.com --dork-category files --no-banner \
  | strx -st "echo {STRING}" -module "clc:http_probe" -pm
```

---

## Criando uma nova fonte

Adicione o arquivo ao diretório de implementações em `sources/passive/`. A classe deve ter `NAME` igual ao nome do arquivo. Nenhuma outra mudança é necessária, pois o registro é automático.

```python
from sources.base import BaseSource, Dork

class MinhaFonte(BaseSource):
    NAME = 'minha_fonte'
    DESCRIPTION = 'O que essa fonte faz'
    CATEGORY = 'web'              # web | code | source | legal | leak
    SUPPORTS_OPERATORS = True     # False se a fonte não entende site:/ext:/...
    ROTATE_MID_FETCH = True       # False se trocar de proxy no meio quebraria a fonte

    async def fetch(self, dork: Dork) -> set[str]:
        query = self.query_for(dork)   # já rebaixada para termos soltos se preciso
        urls: set[str] = set()
        async with self._make_client() as client:
            resp = await self._get(client, 'https://exemplo/...')   # ou self._post(...)
        return self._filter_urls(urls)  # aplica --filter-* e remove chrome da própria fonte
```

Três regras que não são óbvias:

- **Sempre use `self._get()` / `self._post()`**, nunca `client.get()`/`client.post()` direto. São eles que aplicam o `--rate-limit` e a rotação de proxy - uma fonte que chama o cliente direto escapa dos dois em silêncio.
- **`ROTATE_MID_FETCH = False`** quando a fonte tem um fluxo de várias etapas ligado ao IP (um token obtido numa requisição e gasto na seguinte) ou faz uma requisição com efeito colateral que não pode ser repetida. Ela continua usando proxy - só não troca dentro do mesmo `fetch()`.
- **Nunca deixe `fetch()` levantar exceção** - uma fonte bloqueada ou fora do ar deve contribuir com um conjunto vazio, sem derrubar o restante da execução. A única exceção que atravessa de propósito é a de pool de proxy esgotado, que precisa abortar a execução inteira.

Fontes que usam navegador (Playwright) pegam o proxy com `self.browser_proxy()` e avisam o pool de bloqueio com `self.report_block()`.

---

## Banners

A arte ASCII em `core/banner/asciiart/*.txt` é a mesma família visual do [string-x](https://github.com/MrCl0wnLab/string-x) e do resto do SimpleRecon: arquivos de texto puro com códigos ANSI já embutidos, um escolhido aleatoriamente a cada execução. Os placeholders `[VERSION]`/`[DESCRIPTION]` são substituídos por `core/settings.py` em tempo de exibição. `--no-color` (ou `NO_COLOR`, ou stdout não sendo um TTY) remove os códigos ANSI sem trocar o arquivo.

---


## 📄 LICENÇA

Este projeto está licenciado sob a Licença Apache. Veja o arquivo [LICENSE](LICENSE) para detalhes.

## 👨‍💻 AUTOR

**MrCl0wn**
- 🌐 **Blog**: [http://blog.mrcl0wn.com](http://blog.mrcl0wn.com)
- 🐙 **GitHub**: [@MrCl0wnLab](https://github.com/MrCl0wnLab)
- 🐦 **Twitter**: [@MrCl0wnLab](https://twitter.com/MrCl0wnLab)
- 📧 **Email**: mrcl0wnlab\@\gmail.com


---

## Contribuições ✨ <a name="contribuicoes"></a>

Contribuições de qualquer tipo são bem-vindas!

<a href="https://github.com/osintbrazuca/SimpleReconDorking/graphs/contributors">
  <img src="https://contributors-img.web.app/image?repo=osintbrazuca/SimpleReconDorking&max=500" alt="Lista de contribuidores" width="100%"/>
</a>
    

---

<div align="center">

**⭐ Se este projeto foi útil, considere dar uma estrela!**

**💡 Sugestões e feedbacks são sempre bem-vindos!**

**💀 Hacker Hackeia!**

</div>