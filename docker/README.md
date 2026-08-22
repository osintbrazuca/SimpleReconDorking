# Docker

Roda o SimpleReconDorking em contêiner, sem precisar de Python instalado na máquina.

## Build

São dois caminhos de build, e ambos produzem a mesma imagem `docker/simplerecondorking`.

### Opção A: a partir do código local (`docker/Dockerfile`)

Faça o build a partir da **raiz do repositório** (o contexto precisa incluir o projeto inteiro):

```bash
docker build -t docker/simplerecondorking -f docker/Dockerfile .
```

### Opção B: direto do GitHub (`docker/Dockerfile.remote`)

Não precisa de checkout local. Este Dockerfile clona o projeto sozinho, então o contexto de build é ignorado:

```bash
# com um contexto descartável
docker build -t docker/simplerecondorking -f docker/Dockerfile.remote .

# sem contexto nenhum (mandando o Dockerfile pelo pipe)
docker build -t docker/simplerecondorking - < docker/Dockerfile.remote

# sem nada clonado, buildando a partir da URL crua
curl -sSL https://raw.githubusercontent.com/osintbrazuca/SimpleReconDorking/master/docker/Dockerfile.remote \
  | docker build -t docker/simplerecondorking -
```

Para fixar um branch, tag ou fork, use build args:

```bash
docker build -t docker/simplerecondorking -f docker/Dockerfile.remote \
  --build-arg REF=v1.0.0 \
  --build-arg REPO_URL=https://github.com/osintbrazuca/SimpleReconDorking.git .
```

## Execução

Tudo que vier depois do nome da imagem é repassado direto para o `python simplerecondorking.py`:

```bash
# O exemplo principal
docker run --rm docker/simplerecondorking -d 'site:target.com ext:sql'

# Sem argumentos -> ajuda
docker run --rm docker/simplerecondorking

# Listar fontes / perfis / dorks / exemplos
docker run --rm docker/simplerecondorking --list-sources
docker run --rm docker/simplerecondorking --list-profiles
docker run --rm docker/simplerecondorking --list-category

# Pronto para pipe (saída fora de TTY sai sem cor automaticamente)
docker run --rm docker/simplerecondorking -t target.com --dork-category files --no-banner | httpx -silent

# Saída interativa e colorida
docker run --rm -it docker/simplerecondorking -t target.com --dork-category files --profile web
```

## Persistindo dados (resultados, log de comandos, jobs do watch)

> [!WARNING]
> Com `--rm` o contêiner é efêmero e tudo que ele gravou é descartado ao terminar.
> Monte um diretório do host e aponte o `--db` para ele para manter os resultados.

```bash
mkdir -p data
docker run --rm -v "$PWD/data:/app/data" \
  docker/simplerecondorking -t target.com --dork-category files --db /app/data/target.db
```

O log de comandos e o agendador `--watch` ficam em `config/system.db` dentro da imagem. Para preservá-los
entre execuções, monte um arquivo do host por cima:

```bash
touch config/system.db
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/config/system.db:/app/config/system.db" \
  docker/simplerecondorking -t target.com --dork-category files --db /app/data/target.db
```

## Fontes `mojeek`, `ecosia`, `swisscows`, `so` e `dogpile` (precisam de navegador)

A imagem **não** inclui o Playwright/Chromium (o mesmo binário de ~150MB que a instalação local trata como dependência opcional) - dentro do contêiner, as cinco fontes se autodesabilitam com uma mensagem em `-v 1`, igual ao comportamento sem `requirements-browser.txt` local. Todo o resto da ferramenta, incluindo as demais 20 fontes, funciona normalmente. Para usar `mojeek`/`ecosia`/`swisscows`/`so`/`dogpile`, rode a partir da instalação local em vez do Docker.

## Proxy

As flags de proxy funcionam normalmente no contêiner - inclusive `--proxy-file`, desde que o arquivo esteja montado:

```bash
docker run --rm -v "$PWD/proxies.txt:/app/proxies.txt:ro" \
  docker/simplerecondorking -d 'site:target.com' --proxy-file /app/proxies.txt \
  --proxy-rotate round-robin --proxy-rotate-status 403,429
```

> [!IMPORTANT]
> Um proxy em `127.0.0.1` do **host** não é alcançável de dentro do contêiner: ali `127.0.0.1` é o próprio contêiner. Use `--network host`, ou aponte para `host.docker.internal`, ou use o IP da rede do Docker.

## Chaves de API

As chaves **não** ficam embutidas na imagem. Monte seu `config/api_keys.json` em modo somente leitura
quando precisar das fontes autenticadas (`brave`, `github`, `intelx`, `publicwww`):

```bash
docker run --rm \
  -v "$PWD/config/api_keys.json:/app/config/api_keys.json:ro" \
  docker/simplerecondorking -d 'site:target.com' --profile full
```

> [!IMPORTANT]
> Monte o arquivo em modo somente leitura (`:ro`). Sem ela, as fontes que exigem chave
> simplesmente não retornam nada e a ferramenta continua funcionando.

## Monitoramento contínuo (`--watch`)

O agendador é um processo de primeiro plano que roda continuamente, então execute-o em segundo plano com o banco de sistema persistido:

```bash
# Registrar jobs (grava no config/system.db montado)
docker run --rm -v "$PWD/config/system.db:/app/config/system.db" \
  docker/simplerecondorking -t target.com --dork-category files --profile fast --db /app/data/target.db --quiet \
  --watch-add "0,15,30,45 * * * *"

# Rodar o daemon em segundo plano
docker run -d --name dorking-watch \
  -v "$PWD/data:/app/data" \
  -v "$PWD/config/system.db:/app/config/system.db" \
  docker/simplerecondorking --watch

docker logs -f dorking-watch     # ver cada comando disparado
docker stop dorking-watch        # parar o agendador
```

> [!NOTE]
> Os jobs agendados rodam **dentro** do mesmo contêiner, como subprocessos do
> `python simplerecondorking.py ...`.
