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

As capturas de falha contêm a área cliente do Roblox, o recorte, a imagem preparada para o Tesseract e a região destacada. São limitadas a duas amostras por análise; os diagnósticos mantêm no máximo dez pastas e as imagens compactas de auditoria, no máximo vinte. No Python, os arquivos ficam em `diagnostico/`; no EXE, em `%LOCALAPPDATA%\GPO_AutoFarm_v11\diagnostico\`.

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
