# GPO_AutoFarm_v11

Projeto de estudo em Python (Windows), com interface em Tkinter, gravação/reprodução de arquivos TinyTask `.rec`, OCR dos Candies, relógio manual sincronizado e controle de compra. Esta versão para GitHub contém **todo o código-fonte, os três `.rec` padrão e os testes**, sem a compilação nem os arquivos temporários.

## Para executar pelo Python

1. Instale Python para Windows e o **Tesseract OCR** (programa externo necessário para ler Candies).
2. Extraia o projeto e execute `INSTALAR_DEPENDENCIAS.cmd`, ou rode `python -m pip install -r requirements.txt`.
3. Execute `ABRIR_AUTOFARM.cmd`, ou `python main.py`.
4. Confira os três arquivos `.rec`, sincronize o tempo mostrado pelo servidor e teste o OCR antes de iniciar. F12 inicia/para; F8 inicia/termina a gravação (valores padrão).
5. Se o OCR ou o relógio não estiverem confiáveis, **não autorize compras**; teste o primeiro ciclo supervisionando.

Você pode selecionar suas próprias gravações na interface. O `config.json` local não está no GitHub: o aplicativo cria suas configurações na primeira execução. As gravações originais ficam em `gravacoes/`.

O EXE guarda os dados locais em `%LOCALAPPDATA%\GPO_AutoFarm_v11\`. Ao abrir uma versão nova sem configuração existente, ele copia automaticamente o `config.json` da pasta `%LOCALAPPDATA%\RobloxAutoFarm\` da versão anterior.

### Testar e calibrar Candies

Abra o Roblox, equipe manualmente o item dos Candies e clique em **Testar OCR**. O AutoFarm oculta sua janela, confirma o foco do Roblox e mostra o resultado sem executar gravações ou compras. Se necessário, use **Calibrar Candies** para selecionar visualmente o contador; depois consulte as imagens e `diagnostico.txt` em **Abrir diagnóstico**. O log diferencia ausência do contador, região inválida, texto não reconhecido, divergência, indisponibilidade do Tesseract e falha de captura.

O ROI padrão foi ampliado para `(580, 535, 790, 610)`, em coordenadas normalizadas à área cliente do Roblox. Uma configuração que ainda contenha o antigo padrão estreito é migrada automaticamente. A calibração serve como região de busca: o contador é localizado pela cor dentro dela e os recortes OCR são derivados dos limites visuais detectados, com margem. O sistema classifica separadamente candidatos completos válidos, texto malformado, texto inconclusivo e contradições. A largura geométrica do numerador impede que uma saída curta como `09` seja tratada como um segundo valor completo quando os dígitos visíveis ocupam espaço para três; essa leitura fica inconclusiva. A rota alternativa valida o contador completo somente com formato integral `n/500`. Duas interpretações completas válidas diferentes bloqueiam a leitura, enquanto strings como `500/0` são registradas como malformadas, não como valores ou contradições. Não se estima nenhum dígito ausente.

O botão de teste só funciona com automação e gravação paradas. Durante o teste, o botão fica bloqueado e a reprodução ou uma nova gravação não podem ser iniciadas; o resultado mostra o ROI, o contador localizado e o numerador isolado. Os arquivos de diagnóstico incluem `contador_localizado.png`, `numerador.png` e `regiao_analisada.png`, além da captura, recorte, preparação e `diagnostico.txt`.

Falhas do Tesseract e da captura são classificadas sem interromper a reprodução. Somente timeouts do Tesseract e erros de captura `OSError` com códigos transitórios reconhecidos recebem uma nova tentativa limitada; erros permanentes ou não classificados não são repetidos. Falhas e tentativas não reconhecidas não contam como leituras válidas. A captura e o OCR são serializados em um lock usado pela thread de análise, não pela thread que reproduz o `.rec`. O tipo, etapa, mensagem, componentes de cor, layouts/separadores candidatos, retângulo efetivamente enviado ao Tesseract, leituras brutas e traceback completo ficam nos diagnósticos; o recorte é salvo como `recorte_enviado_tesseract.png`. As capturas de falha durante uma análise automática são limitadas a duas amostras por análise; os diagnósticos mantêm no máximo dez pastas e as imagens compactas de auditoria, no máximo vinte. No Python, os arquivos ficam em `diagnostico/`; no EXE, em `%LOCALAPPDATA%\GPO_AutoFarm_v11\diagnostico\`.

Implementação relacionada: `main.py` define o ROI, migra o padrão antigo, localiza o contador em `locate_candies_counter`, classifica e reconhece as rotas em `analyze_candies`/`run_tesseract_variants`, acumula somente amostras confirmadas em `accumulate_analysis_result` e salva evidências por caminho em `save_candies_diagnostic`. `seguranca_candies.avaliar_leituras` permanece inalterada: exige pelo menos cinco leituras unânimes, recentes e em instantes distintos, e bloqueia contradições válidas. `test_candies_ocr.py` inclui capturas reais, inclusive o diagnóstico `candies_20261029_135445_701718100`, textos malformados, conflito entre rotas, falhas técnicas, estabilidade temporal e bloqueio do teste manual durante a automação; `test_seguranca_candies.py` continua cobrindo os limites de compra. Execute `python -m unittest discover -s Roblox_AutoFarm_v11 -v` para validar.

O Tesseract é externo ao EXE. O aplicativo localiza instalações comuns do Windows e confirma que o executável responde antes de iniciar; um caminho salvo inválido não impede o uso de outra instalação encontrada.

## Criar um EXE menor, sem bibliotecas alheias

No Windows, execute **`COMPILAR_APLICATIVO.cmd`**. Ele cria `.build-venv` (ambiente isolado), instala apenas as três bibliotecas em `requirements.txt` e o PyInstaller, e compila `dist/GPO_AutoFarm_v11/GPO_AutoFarm_v11.exe` em modo `--onedir`. **Não** utiliza as bibliotecas de outros projetos instaladas no seu Python global.

Depois, se quiser instalador com termos, abra `AutoFarm_Instalador.iss` no Inno Setup e compile. O instalador aparece em `instalador/` como `GPO_AutoFarm_v11_Setup.exe`. O tamanho instalado corresponde aos arquivos de `dist/GPO_AutoFarm_v11/` **mais** eventuais programas externos instalados separadamente (como Tesseract). Não há tamanho exato prometido antes da compilação no seu Windows.

**Importante:** o AutoFarm não incorpora automaticamente o executável do Tesseract ao `dist/`; ele deve existir no computador, a menos que você configure sua própria distribuição dele. Um instalador `.exe` sem assinatura digital pode ser bloqueado pelo Smart App Control do Windows mesmo que o projeto seja seu. Não desative a segurança do Windows apenas para executar o app.

## GitHub e tamanho

- `build/`, `dist/`, `instalador/` são produtos da compilação: **não comitar**.
- `.build-venv/`, `__pycache__/`, `config.json`, `diagnostico/` são dados/arquivos locais: **não comitar**.
- O ZIP original duplicava executáveis de compilação, instalador e centenas de bibliotecas. GitHub precisa só do código e arquivos-fonte.
- Os testes estão preservados e podem ser executados em Windows com `python -m unittest discover -v`.

Projeto independente, não oficial do Roblox ou TinyTask. Respeite as regras do jogo e suas limitações de automação.
