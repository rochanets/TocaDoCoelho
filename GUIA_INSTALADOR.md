# Guia de Compilação do Instalador Windows

## 📋 Requisitos

Para compilar o instalador do **Toca do Coelho**, você precisa de:

1. **NSIS (Nullsoft Scriptable Install System)**
   - Baixe em: https://nsis.sourceforge.io/Download
   - Versão recomendada: 3.09 ou superior
   - Instale com as opções padrão

2. **Windows 7 ou superior**

## 🚀 Como Compilar

### Passo 1: Instalar NSIS

1. Acesse: https://nsis.sourceforge.io/Download
2. Baixe o instalador (NSIS 3.09 ou superior)
3. Execute o instalador
4. Deixe as opções padrão
5. Clique em "Install"

### Passo 2: Compilar o Instalador

1. Abra o **Prompt de Comando** na pasta do projeto
2. Execute: `BUILD_INSTALLER.bat`
3. Aguarde a compilação (leva alguns segundos)
4. O arquivo `TocaDoCoelho-1.0.0-Setup.exe` será criado

### Passo 3: Distribuir

O arquivo `TocaDoCoelho-1.0.0-Setup.exe` está pronto para distribuir!

## 📦 O que o Instalador Faz

✅ Instala o aplicativo em `C:\Program Files\TocaDoCoelho`  
✅ Cria atalho na **Área de Trabalho**  
✅ Cria atalho no **Menu Iniciar**  
✅ Instala dependências Python automaticamente  
✅ Registra no **Adicionar/Remover Programas**  
✅ Cria desinstalador completo  

## 🎯 Como Usar o Instalador

1. Duplo clique em `TocaDoCoelho-1.0.0-Setup.exe`
2. Siga as instruções do instalador
3. Clique em "Instalar"
4. Após instalação, clique em "Concluir"
5. Um atalho será criado na Área de Trabalho
6. Duplo clique no atalho para abrir o aplicativo

## 🔧 Customizações

Para modificar o instalador:

1. Edite o arquivo `installer.nsi`
2. Altere as configurações desejadas (nome, versão, etc.)
3. Execute `BUILD_INSTALLER.bat` novamente

### Variáveis Principais

```nsi
Name "Toca do Coelho - Registro de Atividades"  ; Nome do programa
OutFile "TocaDoCoelho-1.0.0-Setup.exe"         ; Nome do arquivo .exe
InstallDir "$PROGRAMFILES\TocaDoCoelho"        ; Pasta de instalação
```

## 📝 Notas Importantes

- O instalador requer **Python 3.7+** instalado no Windows
- Se Python não estiver no PATH, o instalador tentará instalar as dependências mesmo assim
- O aplicativo cria uma pasta em `C:\Users\[Usuário]\AppData\Roaming\toca-do-coelho` para dados
- A desinstalação remove todos os arquivos de instalação, mas **preserva os dados do usuário**

## ❓ Problemas Comuns

### "NSIS não está instalado"
- Baixe e instale NSIS: https://nsis.sourceforge.io/Download
- Reinicie o Prompt de Comando após instalar

### "Erro ao compilar"
- Verifique se todos os arquivos estão na pasta
- Verifique se o arquivo `installer.nsi` não foi modificado incorretamente

### "Python não encontrado"
- Instale Python: https://www.python.org/downloads/
- Marque "Add Python to PATH" durante a instalação

## 📞 Suporte

Para mais informações sobre NSIS, visite: https://nsis.sourceforge.io/

---

**Toca do Coelho v1.0.0** - Registro de Atividades
