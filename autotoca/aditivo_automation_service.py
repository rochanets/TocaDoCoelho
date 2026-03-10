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


def _resolve_form_context(page):
    frame = page
    for ifr in page.locator('iframe').all():
        try:
            name = ifr.get_attribute('name') or ''
            title = ifr.get_attribute('title') or ''
            if 'Forms' in title or 'office' in name.lower():
                frame = page.frame_locator(f"iframe[name='{name}']")
                break
        except Exception:
            continue
    return frame


def run_aditivo_automation(*, payload: dict, form_url: str, submit: bool, headful: bool, screenshots_dir: Path, logger: logging.Logger):
    """
    Executa a automação do formulário Microsoft Forms usando Playwright.
    O frontend já abre a aba, então aqui apenas preenchemos os dados.
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

    browser = None
    context = None
    page = None

    try:
        step('Iniciando Playwright para preencher formulário...')
        
        with sync_playwright() as p:
            # Usar o perfil do usuário do Chrome
            user_data_dir = _get_chrome_user_data_dir()
            launch_args = {
                'channel': 'chrome',
                'headless': False,  # Sempre headful para que o usuário veja
            }
            
            # Se temos um diretório de dados válido, usar o perfil do usuário
            if os.path.exists(user_data_dir):
                launch_args['args'] = [
                    f'--user-data-dir={user_data_dir}',
                    '--no-first-run',
                    '--no-default-browser-check',
                ]
                step(f'Usando perfil do Chrome: {user_data_dir}')
            
            browser = p.chromium.launch(**launch_args)
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
                    
                    # Verificar se chegou no formulário
                    if page.get_by_role('combobox', name='Empresa do grupo Stefanini').count() > 0:
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
                page.wait_for_selector('[role="combobox"]', timeout=30000)
            except Exception as e:
                logger.warning(f'[AutoToca] Timeout aguardando formulário: {e}')

            # Campos via label / role robustos
            try:
                step('Preenchendo campo 1 (Empresa Stefanini).')
                page.get_by_role('combobox', name='Empresa do grupo Stefanini').select_option(label=payload['empresaGrupoStefanini'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 1: {e}')
                step(f'Erro ao preencher campo 1: {str(e)[:100]}')

            try:
                step('Preenchendo campo 2 (Razão social).')
                page.get_by_label('Razão Social - Parte Contrária').fill(payload['contaSelecionada'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 2: {e}')
                step(f'Erro ao preencher campo 2: {str(e)[:100]}')

            try:
                step('Preenchendo campo 3 (Endereço).')
                page.get_by_label('Endereço Atualizado - Parte Contrária').fill(payload['enderecoFinalConfirmado'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 3: {e}')
                step(f'Erro ao preencher campo 3: {str(e)[:100]}')

            try:
                step('Preenchendo campo 4 (Minuta própria).')
                page.get_by_role('radio', name=payload['tipoMinuta']).check()
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 4: {e}')
                step(f'Erro ao preencher campo 4: {str(e)[:100]}')

            try:
                step('Preenchendo campo 5 (Contrato Salesforce).')
                page.get_by_label('Há número de contrato criado no Sales Force? Se sim, informar.').fill(payload['numeroContratoSalesforce'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 5: {e}')
                step(f'Erro ao preencher campo 5: {str(e)[:100]}')

            try:
                step('Preenchendo campo 6 (Data assinatura).')
                page.get_by_label('Data de assinatura do Contrato original').fill(payload['dataAssinaturaContratoOriginal'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 6: {e}')
                step(f'Erro ao preencher campo 6: {str(e)[:100]}')

            try:
                step('Upload campo 7 (Aditivos anteriores).')
                if payload.get('arquivosAditivosAnteriores'):
                    page.get_by_label('Enviar cópia de todos os aditivos anteriores assinados por ambas partes').set_input_files(payload['arquivosAditivosAnteriores'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao fazer upload campo 7: {e}')
                step(f'Erro ao fazer upload campo 7: {str(e)[:100]}')

            try:
                step('Upload campo 8 (Contrato original).')
                if payload.get('arquivosContratoOriginal'):
                    page.get_by_label('Enviar cópia do Contrato original assinado por ambas partes').set_input_files(payload['arquivosContratoOriginal'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao fazer upload campo 8: {e}')
                step(f'Erro ao fazer upload campo 8: {str(e)[:100]}')

            try:
                step('Campo 9 (Minuta para validação).')
                if payload.get('arquivosMinutaCliente'):
                    page.get_by_label('Cliente encaminhou minuta para validação? Se sim, encaminhar documento').set_input_files(payload['arquivosMinutaCliente'])
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao fazer upload campo 9: {e}')
                step(f'Erro ao fazer upload campo 9: {str(e)[:100]}')

            try:
                step('Campo 10 (Reajuste de valores).')
                page.get_by_role('radio', name=payload['haveraReajusteValores']).check()
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 10: {e}')
                step(f'Erro ao preencher campo 10: {str(e)[:100]}')

            # Se houver reajuste, preencher campos 11 e 12
            if payload.get('haveraReajusteValores') == 'Sim':
                try:
                    step('Campo 11 (Índice de reajuste).')
                    if payload.get('indiceReajuste'):
                        page.get_by_label('Se sim, descrever o índice, data base e valores atualizados já com o reajuste').fill(payload['indiceReajuste'])
                except Exception as e:
                    logger.error(f'[AutoToca] Erro ao preencher campo 11: {e}')
                    step(f'Erro ao preencher campo 11: {str(e)[:100]}')
                
                try:
                    step('Campo 12 (Aprovação do CEO).')
                    if payload.get('arquivosAprovacaoCEO'):
                        page.get_by_label('Há aprovação para aplicação de reajuste diferente do previsto em Contrato? (Necessita de acordo do CEO Brasil).').set_input_files(payload['arquivosAprovacaoCEO'])
                except Exception as e:
                    logger.error(f'[AutoToca] Erro ao fazer upload campo 12: {e}')
                    step(f'Erro ao fazer upload campo 12: {str(e)[:100]}')

            page.screenshot(path=str(screenshots_dir / '02-form-filled.png'), full_page=True)

            if submit:
                try:
                    step('submit=true: enviando formulário.')
                    page.get_by_role('button', name='Enviar').click()
                    page.screenshot(path=str(screenshots_dir / '03-form-submitted.png'), full_page=True)
                except Exception as e:
                    logger.error(f'[AutoToca] Erro ao enviar formulário: {e}')
                    step(f'Erro ao enviar formulário: {str(e)[:100]}')
            else:
                step('submit=false: formulário preenchido sem envio automático.')
                step('Aguardando ação do usuário (janela permanecerá aberta)...')

            # Não fechar o navegador se headful
            if not headful:
                context.close()
                browser.close()

    except Exception as e:
        logger.exception(f'[AutoToca] Erro geral na automação: {e}')
        step(f'Erro geral: {str(e)[:200]}')
        # Tentar fechar recursos em caso de erro
        try:
            if context:
                context.close()
            if browser:
                browser.close()
        except:
            pass

    (screenshots_dir / 'execution-log.json').write_text(
        json.dumps({'created_at': datetime.now().isoformat(), 'steps': execution_log}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    return execution_log
