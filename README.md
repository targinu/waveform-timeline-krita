# Waveform Timeline (plugin para Krita)

Docker para o Krita que decodifica o áudio embutido no documento de
animação (via `ffmpeg`), desenha a waveform alinhada ao eixo de frames
e mantém tudo sincronizado com a Linha do Tempo da Animação nativa —
como uma trilha de áudio de editor de vídeo, embaixo dos frames.

## Funcionalidades

- Desenha a waveform (min/max por bloco) do áudio do documento atual.
- Acompanha o **scroll horizontal e o zoom** da Linha do Tempo da
  Animação nativa do Krita, então as colunas da waveform ficam
  alinhadas com as colunas de frames.
- Clicar ou arrastar o mouse sobre a waveform pula o frame atual do
  documento para aquele ponto.
- Arrastar o mouse sobre a waveform toca um trecho curto do áudio
  daquele ponto (preview tipo "scrub" de editor de vídeo), via
  `ffplay`.
- O indicador de frame acompanha a reprodução nativa (Play) da
  animação, incluindo mudanças de velocidade no controle nativo.

## Requisitos

- Krita 5.2 ou mais recente (PyQt5 ou PyQt6, plugin funciona com os dois).
- **ffmpeg** instalado e disponível no `PATH` do sistema (usado para
  decodificar o áudio e tocar os trechos de preview).
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg` (ou o gerenciador de pacotes da sua distro)

## Instalação

### Opção 1: script de instalação (recomendado)

```sh
git clone <url-do-repo>
cd waveform-timeline-krita
python install.py
```

O script detecta automaticamente a pasta de recursos do Krita
(Windows, Linux e macOS) e copia os arquivos do plugin pra lá. Se não
conseguir detectar sozinho, ele pede pra você colar o caminho — pra
descobrir esse caminho manualmente, abra o Krita e vá em
**Configurações → Gerenciar Recursos → Abrir Pasta de Recursos**.

### Opção 2: copiar manualmente

Copie `waveform_timeline.desktop` e a pasta `waveform_timeline/` pra
dentro de `<pasta de recursos do Krita>/pykrita/`. Exemplos de pasta
de recursos por sistema:

| Sistema | Caminho típico |
|---|---|
| Windows | `%APPDATA%\krita` |
| Linux | `~/.local/share/krita` |
| macOS | `~/Library/Application Support/krita` |

## Ativando o plugin no Krita

1. Feche o Krita completamente (se estiver aberto) e abra de novo.
2. **Configurações → Configurar o Krita → Gerenciador de Plugins
   Python**, marque **Waveform Timeline** e reinicie o Krita quando
   for pedido.
3. **Configurações → Painéis → Waveform Timeline** pra exibir o painel.
4. (Opcional, recomendado) Arraste a aba do painel pra encaixar logo
   abaixo da **Linha do Tempo da Animação** nativa, ocupando a largura
   toda — assim a waveform fica alinhada como uma trilha de áudio.

## Uso

- Abra um documento de animação com uma trilha de áudio.
- O painel mostra o nome do arquivo, a duração e o fps assim que
  encontra o áudio. Use **Recarregar** se trocar o arquivo de áudio.
- Clique em qualquer ponto da waveform pra pular o frame atual pra lá.
- Clique e arraste pra "escutar" o áudio enquanto navega pelos picos.

## Limitações conhecidas

- A sincronização de scroll/zoom e do indicador de frame durante o
  Play dependem de detalhes internos do Krita que não fazem parte da
  API pública de scripting — podem parar de funcionar em versões
  futuras do Krita.
- Durante o Play nativo, o Krita não expõe a posição real de
  reprodução via scripting (nem `currentTime()`, nem o estado dos
  widgets da Linha do Tempo refletem isso). O indicador acompanha por
  **estimativa**: mede o tempo decorrido e calibra a taxa real de
  avanço comparando com a posição real a cada pausa. Isso significa
  que a primeira reprodução após abrir o documento pode ficar um
  pouco imprecisa até a calibração se ajustar (a partir da primeira
  pausa, fica bem mais preciso).

## Como funciona por baixo dos panos

O plugin não decodifica o áudio inteiro pra tocar — ele só gera um
envelope (min/max por bloco) via `ffmpeg` pra desenhar a waveform, e
usa `ffplay` sob demanda pra tocar trechos curtos ao arrastar o mouse.
Isso evita depender de bibliotecas de áudio adicionais (como
`QtMultimedia` ou `sounddevice`), que podem não estar disponíveis no
Python embutido do Krita — `ffmpeg`/`ffplay` funcionam do mesmo jeito
em Windows, Linux e macOS.
