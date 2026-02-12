# Toca do Coelho - Sistema de Gestão de Clientes

Sistema profissional de gestão de clientes com interface moderna estilo iOS.

## 📦 Instalação (Recomendado)

### Windows (Instalador)

1. **Baixe** o arquivo `TocaDoCoelho-1.0.0-Setup.exe`
2. **Duplo clique** para iniciar a instalação
3. Siga as instruções do instalador
4. Um atalho será criado na **Área de Trabalho**
5. Duplo clique no atalho para abrir

**Vantagens:**
- ✅ Instalação automática de dependências
- ✅ Atalho na Área de Trabalho
- ✅ Atalho no Menu Iniciar
- ✅ Registrado em Adicionar/Remover Programas
- ✅ Desinstalação completa
- ✅ Sem terminal visível

## 🚀 Instalação Manual (Alternativa)

Se preferir não usar o instalador:

### Requisitos
- **Python 3.7+** instalado e adicionado ao PATH

### Passos

1. **Extraia** o arquivo ZIP em qualquer pasta
2. **Abra o Prompt de Comando** na pasta extraída
3. **Execute** `INSTALAR.bat` (apenas uma vez)
4. **Reinicie o computador** (opcional, mas recomendado)

### Como usar

1. **Execute** `INICIAR.bat` (duplo clique)
2. O navegador abrirá automaticamente em `http://localhost:3000`
3. O sistema estará pronto para usar!

## 📋 Funcionalidades

✅ **Dashboard** - Visualize todos os clientes com status  
✅ **Gestão de Clientes** - Adicione, edite e delete clientes  
✅ **Upload de Foto** - Adicione fotos aos clientes (em círculo)  
✅ **Atividades** - Registre contatos e interações com edição  
✅ **Report** - Exporte dados em CSV  
✅ **Status Automático** - Atualiza conforme atividades registradas  

## 📊 Regra de Status

- 🟢 **Verde (Em dia)**: Menos de 7 dias sem contato
- 🟡 **Amarelo (Atenção)**: 7 a 14 dias sem contato
- 🔴 **Vermelho (Atrasado)**: Mais de 14 dias sem contato

## 💾 Dados

Os dados são salvos em:
- **Windows**: `C:\Users\[SeuUsuário]\AppData\Roaming\toca-do-coelho\`
- **Mac/Linux**: `~/.toca-do-coelho/`

## 🔄 Atualização para v1.0.0

Se você está atualizando de uma versão anterior:

1. **Execute** `RESETAR_BANCO.bat` (deleta o banco de dados antigo)
2. **Execute** `INICIAR.bat` (cria novo banco com schema atualizado)

**ATENÇÃO**: Isso vai deletar todos os dados anteriores!

## ❓ Problemas Comuns

### Python não encontrado
- Instale Python de https://www.python.org/downloads/
- **IMPORTANTE**: Marque "Add Python to PATH" durante a instalação
- Reinicie o computador após instalar

### Porta 3000 já em uso
- Feche o navegador e tente novamente
- Se persistir, reinicie o computador

### Dados não salvam
- Verifique se tem permissão de escrita na pasta AppData/Roaming
- Tente executar como Administrador

### Erro ao salvar atividade
- Execute `RESETAR_BANCO.bat` para resetar o banco de dados
- Isso resolve problemas de schema incompatível

## 🛠️ Compilar Instalador

Para compilar o instalador Windows (`.exe`):

1. Instale NSIS: https://nsis.sourceforge.io/Download
2. Abra o Prompt de Comando na pasta do projeto
3. Execute: `BUILD_INSTALLER.bat`
4. O arquivo `TocaDoCoelho-1.0.0-Setup.exe` será criado

Veja `GUIA_INSTALADOR.md` para mais detalhes.

## 📝 Versão

**Toca do Coelho v1.0.0** - Registro de Atividades

---

Desenvolvido com ❤️ para gerenciar seus clientes de forma eficiente.
