import json
import logging
import time
import os
import platform
from datetime import datetime
from pathlib import Path


def _get_chrome_user_data_dir():
    """Obtém o diretório de dados do usuário do Chrome (perfil padrão)."""
    system = platform.system()
    
    if system == 'Windows':
        return os.path.expanduser(r'~\AppData\Local\Google\Chrome\User Data')
    elif system == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/Google/Chrome')
    else:  # Linux
        return os.path.expanduser('~/.config/google-chrome')


def run_aditivo_automation(*, payload: dict, form_url: str, submit: bool, headful: bool, screenshots_dir: Path, logger: logging.Logger):
    """
    Executa a automação do formulário Microsoft Forms usando Playwright.
    Usa seletores de acessibilidade (ARIA) exatos baseados nos prints do usuário.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError('Playwright não está instalado no ambiente. Instale com: pip install playwright && playwright install chrome') from exc

    screenshots_dir.mkdir(parents=True, exist_ok=True)
    execution_log = []

    def step(message):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        execution_log.append(line)
        logger.info('[AutoToca][ChamadoJuridico] %s', message)

    p = None
    context = None
    page = None

    try:
        step('Iniciando Playwright para preencher formulário...')
        
        p = sync_playwright().start()
        
        # Usar launch_persistent_context para carregar o perfil do usuário
        user_data_dir = _get_chrome_user_data_dir()
        
        if os.path.exists(user_data_dir):
            step(f'Usando perfil do Chrome: {user_data_dir}')
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir,
                    channel='chrome',
                    headless=False,
                )
            except Exception as e:
                logger.warning(f'[AutoToca] Erro ao usar perfil persistente: {e}. Tentando sem perfil.')
                step('Erro ao carregar perfil. Iniciando sem perfil do usuário.')
                browser = p.chromium.launch(channel='chrome', headless=False)
                context = browser.new_context()
        else:
            step('Diretório de perfil não encontrado. Iniciando sem perfil do usuário.')
            browser = p.chromium.launch(channel='chrome', headless=False)
            context = browser.new_context()

        page = context.new_page()

        step('Navegando para o formulário...')
        page.goto(form_url, wait_until='domcontentloaded', timeout=120000)
        page.screenshot(path=str(screenshots_dir / '01-form-open.png'), full_page=True)

        # Aguardar login/MFA com maior tolerância
        login_detected = False
        max_wait_time = 300  # 5 minutos
        wait_interval = 2
        elapsed = 0

        step('Verificando se há login corporativo/MFA...')
        while elapsed < max_wait_time:
            try:
                # Verificar se ainda está em página de login
                if page.get_by_text('Entrar').count() > 0 or page.get_by_text('Sign in').count() > 0:
                    if not login_detected:
                        step('Login corporativo/MFA detectado. Aguardando continuidade manual por até 5 minutos.')
                        login_detected = True
                    time.sleep(wait_interval)
                    elapsed += wait_interval
                    page.reload()
                    continue
                
                # Verificar se chegou no formulário - procurar por qualquer input ou combobox
                if page.locator('[role="combobox"]').count() > 0 or page.locator('input[type="text"]').count() > 0:
                    step('Login concluído. Formulário carregado com sucesso.')
                    break
                
                time.sleep(wait_interval)
                elapsed += wait_interval
            except Exception as e:
                logger.warning(f'[AutoToca] Erro ao verificar login: {e}. Continuando...')
                time.sleep(wait_interval)
                elapsed += wait_interval

        if elapsed >= max_wait_time:
            step('Aviso: Tempo de espera para login excedido. Tentando prosseguir mesmo assim.')

        # Aguardar o formulário estar pronto
        try:
            page.wait_for_selector('[role="combobox"], input[type="text"]', timeout=30000)
        except Exception as e:
            logger.warning(f'[AutoToca] Timeout aguardando formulário: {e}')

        # Aguardar um pouco mais para o formulário ficar totalmente interativo
        time.sleep(3)

        # Campo 1: Empresa Stefanini (combobox)
        try:
            step('Preenchendo campo 1 (Empresa Stefanini).')
            combobox = page.get_by_role('combobox', name='1. Empresa do grupo Stefanini Requer resposta Opção única.').first
            if combobox.count() == 0:
                combobox = page.locator('[role="combobox"]').first
            
            if combobox.count() > 0:
                combobox.click()
                time.sleep(1)
                # Procurar pela opção STEFANINI
                option = page.locator('[role="option"]', has_text='STEFANINI CONSULTORIA').first
                if option.count() > 0:
                    option.click()
                    step('Campo 1 preenchido com sucesso.')
                else:
                    step('Aviso: Opção STEFANINI não encontrada no dropdown.')
            else:
                step('Aviso: Combobox não encontrado.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 1: {e}')
            step(f'Erro ao preencher campo 1: {str(e)[:100]}')

        # Campo 2: Razão Social - Parte Contrária
        try:
            step('Preenchendo campo 2 (Razão Social).')
            # Seletor exato baseado no print do usuário
            field = page.get_by_role('textbox', name='2. Razão Social - Parte Contrária Requer resposta Texto de linha única.').first
            if field.count() > 0:
                field.fill(payload['contaSelecionada'])
                step('Campo 2 preenchido com sucesso.')
            else:
                step('Aviso: Campo 2 não encontrado pelo seletor ARIA.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 2: {e}')
            step(f'Erro ao preencher campo 2: {str(e)[:100]}')

        # Campo 3: Endereço Atualizado - Parte Contrária
        try:
            step('Preenchendo campo 3 (Endereço).')
            # Seletor exato baseado no print do usuário
            field = page.get_by_role('textbox', name='3. Endereço Atualizado - Parte Contrária Requer resposta Texto de linha única.').first
            if field.count() > 0:
                field.fill(payload['enderecoFinalConfirmado'])
                step('Campo 3 preenchido com sucesso.')
            else:
                step('Aviso: Campo 3 não encontrado pelo seletor ARIA.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 3: {e}')
            step(f'Erro ao preencher campo 3: {str(e)[:100]}')

        # Campo 4: Minuta própria Stefanini (radio button)
        try:
            step('Preenchendo campo 4 (Minuta própria Stefanini).')
            # Seletor exato baseado no print do usuário
            radiogroup = page.get_by_role('radiogroup', name='4. Minuta própria Stefanini? Requer resposta Opção única.').first
            if radiogroup.count() > 0:
                option = radiogroup.get_by_role('radio', name=payload['tipoMinuta']).first
                if option.count() > 0:
                    option.click()
                    step('Campo 4 preenchido com sucesso.')
                else:
                    step(f'Aviso: Opção "{payload["tipoMinuta"]}" não encontrada no radiogroup 4.')
            else:
                step('Aviso: Radiogroup 4 não encontrado.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 4: {e}')
            step(f'Erro ao preencher campo 4: {str(e)[:100]}')

        # Campo 5: Número contrato Salesforce
        try:
            step('Preenchendo campo 5 (Número Contrato Salesforce).')
            # Seletor exato baseado no print do usuário
            field = page.get_by_role('textbox', name='5. Há número de contrato criado no Sales Force? Se sim, informar. Requer resposta Texto de linha única.').first
            if field.count() > 0:
                field.fill(payload['numeroContratoSalesforce'])
                step('Campo 5 preenchido com sucesso.')
            else:
                step('Aviso: Campo 5 não encontrado pelo seletor ARIA.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 5: {e}')
            step(f'Erro ao preencher campo 5: {str(e)[:100]}')

        # Campo 6: Data assinatura
        try:
            step('Preenchendo campo 6 (Data assinatura).')
            # Seletor exato baseado no print do usuário
            field = page.get_by_role('textbox', name='6. Data de assinatura do Contrato original Requer resposta Texto de linha única.').first
            if field.count() > 0:
                field.fill(payload['dataAssinaturaContratoOriginal'])
                step('Campo 6 preenchido com sucesso.')
            else:
                step('Aviso: Campo 6 não encontrado pelo seletor ARIA.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 6: {e}')
            step(f'Erro ao preencher campo 6: {str(e)[:100]}')

        # Campo 7: Aditivos anteriores (file upload)
        try:
            step('Upload campo 7 (Aditivos anteriores).')
            if payload.get('arquivosAditivosAnteriores'):
                # Procurar pelo botão de carregar arquivo da pergunta 7
                file_input = page.locator('input[type="file"]').nth(0)
                if file_input.count() > 0:
                    file_input.set_input_files(payload['arquivosAditivosAnteriores'])
                    step('Campo 7 preenchido com sucesso.')
                else:
                    step('Aviso: Campo de upload 7 não encontrado.')
            else:
                step('Campo 7: Nenhum arquivo fornecido.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao fazer upload campo 7: {e}')
            step(f'Erro ao fazer upload campo 7: {str(e)[:100]}')

        # Campo 8: Contrato original (file upload)
        try:
            step('Upload campo 8 (Contrato original).')
            if payload.get('arquivosContratoOriginal'):
                # Procurar pelo botão de carregar arquivo da pergunta 8
                file_input = page.locator('input[type="file"]').nth(1)
                if file_input.count() > 0:
                    file_input.set_input_files(payload['arquivosContratoOriginal'])
                    step('Campo 8 preenchido com sucesso.')
                else:
                    step('Aviso: Campo de upload 8 não encontrado.')
            else:
                step('Campo 8: Nenhum arquivo fornecido.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao fazer upload campo 8: {e}')
            step(f'Erro ao fazer upload campo 8: {str(e)[:100]}')

        # Campo 9: Minuta cliente (file upload)
        try:
            step('Campo 9 (Minuta para validação).')
            if payload.get('arquivosMinutaCliente'):
                # Procurar pelo botão de carregar arquivo da pergunta 9
                file_input = page.locator('input[type="file"]').nth(2)
                if file_input.count() > 0:
                    file_input.set_input_files(payload['arquivosMinutaCliente'])
                    step('Campo 9 preenchido com sucesso.')
                else:
                    step('Aviso: Campo de upload 9 não encontrado.')
            else:
                step('Campo 9: Nenhum arquivo fornecido.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao fazer upload campo 9: {e}')
            step(f'Erro ao fazer upload campo 9: {str(e)[:100]}')

        # Campo 10: Haverá reajuste de valores (radio button)
        try:
            step('Campo 10 (Haverá reajuste de valores).')
            reajuste_value = payload.get('haveraReajusteValores', 'Não')
            # Seletor exato baseado no print do usuário
            radiogroup = page.get_by_role('radiogroup', name='10. Haverá reajuste de valores? Requer resposta Opção única.').first
            if radiogroup.count() > 0:
                option = radiogroup.get_by_role('radio', name=reajuste_value).first
                if option.count() > 0:
                    option.click()
                    step(f'Campo 10 preenchido com "{reajuste_value}" com sucesso.')
                else:
                    step(f'Aviso: Opção "{reajuste_value}" não encontrada no radiogroup 10.')
            else:
                step('Aviso: Radiogroup 10 não encontrado.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 10: {e}')
            step(f'Erro ao preencher campo 10: {str(e)[:100]}')

        # Se houver reajuste, preencher campos 11 e 12
        if payload.get('haveraReajusteValores') == 'Sim':
            try:
                step('Campo 11 (Índice de reajuste).')
                if payload.get('indiceReajuste'):
                    # Seletor ARIA para textarea (pergunta 11)
                    field = page.get_by_role('textbox', name='11. Se sim, descrever o índice, data base e valores atualizados já com o reajuste Requer resposta Texto de várias linhas.').first
                    if field.count() > 0:
                        field.fill(payload['indiceReajuste'])
                        step('Campo 11 preenchido com sucesso.')
                    else:
                        step('Aviso: Campo 11 não encontrado pelo seletor ARIA.')
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 11: {e}')
                step(f'Erro ao preencher campo 11: {str(e)[:100]}')
            
            try:
                step('Campo 12 (Aprovação do CEO).')
                if payload.get('arquivosAprovacaoCEO'):
                    # Procurar pelo botão de carregar arquivo da pergunta 12
                    file_input = page.locator('input[type="file"]').nth(3)
                    if file_input.count() > 0:
                        file_input.set_input_files(payload['arquivosAprovacaoCEO'])
                        step('Campo 12 preenchido com sucesso.')
                    else:
                        step('Aviso: Campo de upload 12 não encontrado.')
                else:
                    step('Campo 12: Nenhum arquivo fornecido.')
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao fazer upload campo 12: {e}')
                step(f'Erro ao fazer upload campo 12: {str(e)[:100]}')

        page.screenshot(path=str(screenshots_dir / '02-form-filled.png'), full_page=True)

        if submit:
            try:
                step('submit=true: enviando formulário.')
                submit_btn = page.get_by_role('button', name='Enviar').first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    page.screenshot(path=str(screenshots_dir / '03-form-submitted.png'), full_page=True)
                    step('Formulário enviado com sucesso.')
                else:
                    step('Aviso: Botão Enviar não encontrado.')
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao enviar formulário: {e}')
                step(f'Erro ao enviar formulário: {str(e)[:100]}')
        else:
            step('submit=false: formulário preenchido sem envio automático.')
            step('Aguardando ação do usuário (janela permanecerá aberta)...')

        # Não fechar o navegador se headful
        if not headful:
            if context:
                context.close()

    except Exception as e:
        logger.exception(f'[AutoToca] Erro geral na automação: {e}')
        step(f'Erro geral: {str(e)[:200]}')
        # Tentar fechar recursos em caso de erro
        try:
            if context:
                context.close()
        except:
            pass
    finally:
        # Fechar playwright
        if p:
            try:
                p.stop()
            except:
                pass

    (screenshots_dir / 'execution-log.json').write_text(
        json.dumps({'created_at': datetime.now().isoformat(), 'steps': execution_log}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    return execution_log
