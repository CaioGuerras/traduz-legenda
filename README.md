# traduz-legenda

Traduz a **legenda em inglês embutida** num vídeo para **português do Brasil** (ou outro idioma) com um modelo de linguagem e
grava `<vídeo>.por.srt` ao lado do arquivo (com `.pt-BR.srt` alguns apps mostram "bretão"). Feito para anime, que quase sempre sai primeiro só com legenda em inglês:
traduz na hora e, quando sair a versão legendada ou dublada em PT-BR, o Sonarr troca o arquivo.

- **Barato:** com o DeepSeek, um episódio de anime custa de **US$ 0,002 a 0,008** (testado no nosso servidor).
- **Escolhe a faixa certa:** a de diálogo em inglês, em texto, não forçada e sem "Signs & Songs" (só lê o cabeçalho com o ffprobe).
- **Confere a resposta:** manda lotes de 60 falas numeradas e só aceita a volta com as mesmas linhas (senão tenta de novo).
- **Mantém o tom:** nomes e honoríficos japoneses (-san, -kun, senpai) ficam; tradução coloquial, como legenda profissional.
- **Integra com Sonarr e Jellyfin:** modo automático para anime sem legenda PT; avisa o Jellyfin que a legenda nova existe.
- Só biblioteca padrão do Python 3 + ffmpeg/ffprobe. Qualquer API compatível com OpenAI (DeepSeek por padrão).

## Uso

```sh
export LLM_API_KEY=...            # chave do DeepSeek (ou de outra API compatível com OpenAI)
./traduz_legenda.py "Episodio 01.mkv"                     # grava "Episodio 01.por.srt"
./traduz_legenda.py *.mkv --lang es                       # outro idioma
./traduz_legenda.py "Episodio 01.mkv" --dry-run           # só mostra a faixa escolhida e quantas falas

# automático: anime do Sonarr importado no último dia, sem áudio nem legenda em português
export SONARR_API_KEY=...  JELLYFIN_URL=http://localhost:8096  JELLYFIN_API_KEY=...
./traduz_legenda.py --sonarr http://localhost:8989 --days 1 --max 6
```

Cron de exemplo (a cada 30 min): `*/30 * * * * LLM_API_KEY=... SONARR_API_KEY=... /caminho/traduz_legenda.py --sonarr http://localhost:8989`

| Variável | Padrão | Para quê |
|---|---|---|
| `LLM_API_KEY` | (obrigatória) | chave da API |
| `LLM_BASE_URL` | `https://api.deepseek.com` | qualquer API compatível com OpenAI |
| `LLM_MODEL` | `deepseek-flash` | modelo |
| `LLM_PRICE_IN` / `LLM_PRICE_OUT` | `0.3` / `1.2` | US$ por milhão de tokens (relatório de custo) |
| `MAX_USD` | `1.0` | para a execução quando passar desse gasto |
| `SONARR_API_KEY` | | modo `--sonarr` |
| `JELLYFIN_URL`, `JELLYFIN_API_KEY` | | avisar o Jellyfin (sem varrer a biblioteca) |

Dica para Sonarr: dê pontos para releases da Crunchyroll (`\b(CR|Crunchyroll)\b`), que quase sempre trazem legenda pt-BR, e
lembre que **"DUAL" no Nyaa quer dizer japonês + inglês**, não português.

---

**English:** translates the English subtitle embedded in a video into Brazilian Portuguese (or `--lang es|fr|it|de|pt`) with any
OpenAI-compatible API (DeepSeek by default, about US$ 0.002-0.008 per anime episode) and writes `<video>.por.srt` (pt-BR) or `<video>.<lang>.srt`. Picks the
English dialogue track (text, not forced, not signs/songs), sends numbered batches and validates the answer, keeps honorifics.
Optional Sonarr mode for anime without a Portuguese track, and Jellyfin notification. Python 3 standard library + ffmpeg. MIT.

Made for CGFLIX, a family-and-friends media server in Brazil. Companion theme: [cgflix-jellyfin-theme](https://github.com/CaioGuerras/cgflix-jellyfin-theme).
