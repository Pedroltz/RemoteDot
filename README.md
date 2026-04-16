# RemoteDot

Dashboard de monitoramento remoto multi-cliente. Permite monitorar múltiplas máquinas Windows a partir de um painel web centralizado.

## Funcionalidades

- **Tela ao vivo** — captura de tela sob demanda ou com auto-refresh
- **Keylog por janela** — registra teclas digitadas agrupadas pela janela em foco, com pesquisa
- **Gerenciador de arquivos** — navegação, download e upload de arquivos remotos
- **Terminal PowerShell** — sessão persistente com histórico de comandos e prompt dinâmico
- **Autenticação** — login com usuários gerenciáveis pelo painel
- **Multi-agente** — múltiplas máquinas conectadas simultaneamente

## Estrutura

```
RemoteDot/
├── server/          # Servidor Node.js (Socket.IO + Express)
├── dashboard/       # Frontend web (SPA, servida pelo servidor)
│   └── public/
│       └── index.html
└── agent/           # Agente Python (roda na máquina monitorada)
    ├── agent.py
    ├── config.ini
    ├── agent.spec   # Build PyInstaller
    ├── build.bat    # Script de compilação
    └── requirements.txt
```

## Requisitos

**Servidor:** Node.js 18+

**Agente:** Python 3.9+ (Windows)

## Instalação

### Servidor

```bash
cd server
npm install
npm start
```

O painel estará disponível em `http://localhost:3000`.

Credenciais padrão: `admin` / `admin` — **altere pelo painel após o primeiro login.**

### Agente (Python direto)

```bash
cd agent
pip install -r requirements.txt
python agent.py
```

Por padrão conecta em `http://localhost:3000`. Para apontar para outro servidor:

```bash
set MONITOR_SERVER=http://SEU_IP:3000
python agent.py
```

### Agente (compilado como .exe)

```bash
cd agent
build.bat
```

O executável é gerado em `agent/dist/agent.exe`. Copie o `agent.exe` e o `config.ini` para a máquina alvo e edite o `config.ini`:

```ini
[agent]
server = http://SEU_IP:3000
```

## Aviso

Esta ferramenta é destinada a uso em máquinas próprias ou com autorização explícita. O uso não autorizado em sistemas de terceiros é ilegal.
