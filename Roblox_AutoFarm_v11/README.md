# GPO_AutoFarm_v11

Projeto de estudo em Python (Windows), com interface em Tkinter, gravação/reprodução de arquivos TinyTask `.rec`, OCR dos Candies, relógio manual sincronizado e controle de compra. Esta versão para GitHub contém **todo o código-fonte, os três `.rec` padrão e os testes**, sem a compilação nem os arquivos temporários.

## Para executar pelo Python

1. Instale Python para Windows. O runtime x64 do Tesseract OCR e o idioma `eng` estao incluidos na pasta `tesseract/`.
2. Extraia o projeto e execute `INSTALAR_DEPENDENCIAS.cmd`, ou rode `python -m pip install -r requirements.txt`.
3. Execute `ABRIR_AUTOFARM.cmd`, ou `python main.py`.
4. Confira os três arquivos `.rec`, sincronize o tempo mostrado pelo servidor e teste o OCR antes de iniciar. F12 inicia/para; F8 inicia/termina a gravação (valores padrão).
5. Se o OCR ou o relógio não estiverem confiáveis, **não autorize compras**; teste o primeiro ciclo supervisionando.

Você pode selecionar suas próprias gravações na interface. O `config.json` local não está no GitHub: o aplicativo cria suas configurações na primeira execução. As gravações originais ficam em `gravacoes/`.

O EXE guarda os dados locais em `%LOCALAPPDATA%\GPO_AutoFarm_v11\`. Ao abrir uma versão nova sem configuração existente, ele copia automaticamente o `config.json` da pasta `%LOCALAPPDATA%\RobloxAutoFarm\` da versão anterior.

### Contador de Rare Chests

O Monitoramento mostra quantas gravações de compra terminaram integralmente, de `0/10` a `10/10`. A quantidade pode ser ajustada manualmente com a automação parada e é salva automaticamente no `config.json`. Ao atingir `10/10`, todas as compras são suspensas, mas os ciclos completos de Coleta e Análise continuam. O contador registra gravações executadas, não confirma que o item entrou no inventário do Roblox.

### Gravações personalizadas e armazenamento

Cada categoria mantém uma única gravação criada por **Gravar agora**: `coleta_personalizada.rec`, `analise_personalizada.rec` ou `compra_personalizada.rec`, em `%LOCALAPPDATA%\GPO_AutoFarm_v11\gravacoes\`, tanto no Python quanto no EXE. Uma gravação nova substitui somente a personalizada correspondente, após validar o `.rec`; seus metadados `.meta.json` são atualizados junto. A seleção é salva no `config.json`. Cancelamentos e falhas não substituem a gravação anterior. **Restaurar padrão** apenas seleciona novamente os três recursos padrão.

Gravações antigas com timestamp e arquivos externos configurados continuam preservados e selecionáveis; não são removidos automaticamente. O compilador inclui somente os três `.rec` padrão, não a pasta inteira de gravações nem as gravações pessoais.

### Testar e calibrar Candies

Abra o Roblox, equipe manualmente o item dos Candies e clique em **Testar OCR**. O AutoFarm oculta sua janela, confirma o foco do Roblox e mostra o resultado sem executar gravações ou compras. Se necessário, use **Calibrar Candies** para selecionar visualmente o contador; depois consulte as imagens e `diagnostico.txt` em **Abrir diagnóstico**. O log diferencia ausência do contador, região inválida, texto não reconhecido, divergência, indisponibilidade do Tesseract e falha de captura.

O ROI padrão foi ampliado para `(580, 535, 790, 610)`, em coordenadas normalizadas à área cliente do Roblox. Uma configuração que ainda contenha o antigo padrão estreito é migrada automaticamente. A calibração serve como região de busca: o contador é localizado pela cor dentro dela e os recortes OCR são derivados dos limites visuais detectados, com margem. O sistema classifica separadamente candidatos completos válidos, texto malformado, texto inconclusivo e contradições. A largura geométrica do numerador impede que uma saída curta como `09` seja tratada como um segundo valor completo quando os dígitos visíveis ocupam espaço para três; essa leitura fica inconclusiva. A rota alternativa valida o contador completo somente com formato integral `n/500`. Duas interpretações completas válidas diferentes bloqueiam a leitura, enquanto strings como `500/0` são registradas como malformadas, não como valores ou contradições. Não se estima nenhum dígito ausente.

O botão de teste só funciona com automação e gravação paradas. Durante o teste, o botão fica bloqueado e a reprodução ou uma nova gravação não podem ser iniciadas; o resultado mostra o ROI, o contador localizado e o numerador isolado. Os arquivos de diagnóstico incluem `contador_localizado.png`, `numerador.png` e `regiao_analisada.png`, além da captura, recorte, preparação e `diagnostico.txt`.

Falhas do Tesseract e da captura são classificadas sem interromper a reprodução. Somente timeouts do Tesseract e erros de captura `OSError` com códigos transitórios reconhecidos recebem uma nova tentativa limitada; erros permanentes ou não classificados não são repetidos. Falhas e tentativas não reconhecidas não contam como leituras válidas. A captura e o OCR são serializados em um lock usado pela thread de análise, não pela thread que reproduz o `.rec`. O tipo, etapa, mensagem, componentes de cor, layouts/separadores candidatos, retângulo efetivamente enviado ao Tesseract, leituras brutas e traceback completo ficam nos diagnósticos; o recorte é salvo como `recorte_enviado_tesseract.png`. Durante a automação, somente falhas, leituras inconclusivas e contradições geram pastas de evidência; o teste manual ainda salva seu diagnóstico. A retenção mantém no máximo cinco pastas de diagnóstico e limita imagens de auditoria soltas a vinte; imagens do relógio também são limitadas às cinco capturas mais recentes. A limpeza roda na inicialização e após salvar evidências, fora da reprodução. `ocr_exceptions.log` mantém no máximo 1 MiB mais uma rotação de 1 MiB. No Python, os arquivos ficam em `diagnostico/`; no EXE, em `%LOCALAPPDATA%\GPO_AutoFarm_v11\diagnostico\`.

Implementação relacionada: `main.py` define o ROI, localiza o contador em `locate_candies_counter`, mantém as rotas e validação em `analyze_candies`/`run_tesseract_variants`, publica gravações pessoais validadas em `publish_custom_recording` e limita diagnósticos em `prune_candies_diagnostics`. A validação temporal em `seguranca_candies.avaliar_leituras` não foi alterada. `test_candies_ocr.py` e `test_seguranca_candies.py` cobrem OCR e compra; `test_storage.py` cobre gravações, metadados, persistência, empacotamento e retenção. Execute `python -m unittest discover -s Roblox_AutoFarm_v11 -v` para validar.

O aplicativo prioriza o Tesseract portátil em `tesseract/`, configura o diretório `tessdata` localmente e testa a execução real do idioma `eng` antes de iniciar. Um caminho antigo salvo em `config.json` não impede o uso do Tesseract incluído. Se o runtime portátil estiver ausente, instalações externas válidas ainda podem ser usadas.

## Criar um EXE menor, sem bibliotecas alheias

No Windows, execute **`COMPILAR_APLICATIVO.cmd`**. Ele valida o Tesseract e o idioma `eng` sem depender do PATH, cria `.build-venv` (ambiente isolado), instala apenas as três bibliotecas em `requirements.txt` e o PyInstaller, compila `dist/GPO_AutoFarm_v11/GPO_AutoFarm_v11.exe` em modo `--onedir` e copia o runtime para `dist/GPO_AutoFarm_v11/tesseract/`. **Não** utiliza as bibliotecas de outros projetos instaladas no seu Python global.

Depois, se quiser instalador com termos, abra `AutoFarm_Instalador.iss` no Inno Setup e compile. O instalador aparece em `instalador/` como `GPO_AutoFarm_v11_Setup.exe`. Tanto o instalador Inno Setup quanto um SFX WinRAR devem incluir a pasta `tesseract/` inteira junto ao EXE. O pacote do Tesseract e suas licenças estao em `tesseract/NOTICE.txt`.

**Importante:** os binários do aplicativo não têm assinatura digital e ainda podem ser bloqueados pelo Smart App Control do Windows. Não desative as proteções do Windows para executar o app.

## GitHub e tamanho

- `build/`, `dist/`, `instalador/` são produtos da compilação: **não comitar**.
- `.build-venv/`, `__pycache__/`, `config.json`, `diagnostico/` são dados/arquivos locais: **não comitar**.
- O runtime Tesseract x64 é uma dependência redistribuída e fica em `tesseract/`; `build/`, `dist/` e `instalador/` continuam sendo produtos locais da compilação.
- Os testes estão preservados e podem ser executados em Windows com `python -m unittest discover -v`.

Projeto independente, não oficial do Roblox ou TinyTask. Respeite as regras do jogo e suas limitações de automação.
