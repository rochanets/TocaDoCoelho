import json
import logging
import time
import os
import platform
import tempfile
import shutil
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


def _try_remote_debugging(logger):
    """Tenta se conectar a uma instância do Chrome já aberta via Remote Debugging."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        chrome_options = Options()
        chrome_options.add_experimental_option('debuggerAddress', 'localhost:9222')
        
        driver = webdriver.Chrome(options=chrome_options)
        logger.info('[AutoToca] Conectado a instância de Chrome existente via Remote Debugging.')
        return driver
    except Exception as e:
        logger.warning(f'[AutoToca] Não foi possível conectar via Remote Debugging: {e}')
        return None


def run_aditivo_automation(*, payload: dict, form_url: str, submit: bool, headful: bool, screenshots_dir: Path, logger: logging.Logger):
    """
    Executa a automação do formulário Microsoft Forms usando Selenium.
    Tenta se conectar a uma instância existente via Remote Debugging ou abre uma nova com perfil temporário.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import Select, WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except Exception as exc:
        raise RuntimeError('Selenium ou webdriver-manager não estão instalados. Instale com: pip install selenium webdriver-manager') from exc

    screenshots_dir.mkdir(parents=True, exist_ok=True)
    execution_log = []

    def step(message):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        execution_log.append(line)
        logger.info('[AutoToca][ChamadoJuridico] %s', message)

    driver = None
    temp_profile_dir = None

    try:
        step('Iniciando Selenium para preencher formulário...')
        
        # Tentar conectar a uma instância existente via Remote Debugging
        step('Tentando conectar a instância de Chrome existente via Remote Debugging...')
        driver = _try_remote_debugging(logger)
        
        if not driver:
            # Se não conseguir, abrir uma nova instância com perfil temporário
            step('Nenhuma instância existente encontrada. Abrindo nova instância com perfil temporário.')
            
            # Criar um diretório temporário para o perfil
            temp_profile_dir = tempfile.mkdtemp(prefix='chrome_profile_')
            
            chrome_options = Options()
            chrome_options.add_argument(f'user-data-dir={temp_profile_dir}')
            chrome_options.add_experimental_option('detach', True)
            prefs = {'profile.default_content_setting_values.notifications': 2}
            chrome_options.add_experimental_option('prefs', prefs)
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            step(f'Nova instância aberta com perfil temporário: {temp_profile_dir}')
        
        step('Navegando para o formulário...')
        driver.get(form_url)
        
        # Aguardar login/MFA com maior tolerância
        login_detected = False
        max_wait_time = 300  # 5 minutos
        wait_interval = 2
        elapsed = 0
        
        step('Verificando se há login corporativo/MFA...')
        while elapsed < max_wait_time:
            try:
                # Verificar se ainda está em página de login
                try:
                    driver.find_element(By.XPATH, "//*[contains(text(), 'Entrar') or contains(text(), 'Sign in')]")
                    if not login_detected:
                        step('Login corporativo/MFA detectado. Aguardando continuidade manual por até 5 minutos.')
                        login_detected = True
                    time.sleep(wait_interval)
                    elapsed += wait_interval
                    driver.refresh()
                    continue
                except:
                    pass
                
                # Verificar se chegou no formulário
                try:
                    driver.find_element(By.CSS_SELECTOR, 'input[type="text"], [role="combobox"]')
                    step('Login concluído. Formulário carregado com sucesso.')
                    break
                except:
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
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="text"], [role="combobox"]'))
            )
        except Exception as e:
            logger.warning(f'[AutoToca] Timeout aguardando formulário: {e}')

        # Aguardar um pouco mais para o formulário ficar totalmente interativo
        time.sleep(3)

        # Campo 1: Empresa Stefanini (combobox)
        try:
            step('Preenchendo campo 1 (Empresa Stefanini).')
            combobox = driver.find_element(By.CSS_SELECTOR, '[role="combobox"]')
            combobox.click()
            time.sleep(1)
            
            # Procurar pela opção STEFANINI
            option = driver.find_element(By.XPATH, "//*[@role='option' and contains(text(), 'STEFANINI CONSULTORIA')]")
            option.click()
            step('Campo 1 preenchido com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 1: {e}')
            step(f'Erro ao preencher campo 1: {str(e)[:100]}')

        # Campo 2: Razão Social - Parte Contrária
        try:
            step('Preenchendo campo 2 (Razão Social).')
            # Procurar pelo input de texto com aria-label contendo "Razão Social"
            field = driver.find_element(By.XPATH, "//input[@type='text' and contains(@aria-label, 'Razão Social')]")
            field.clear()
            field.send_keys(payload['contaSelecionada'])
            step('Campo 2 preenchido com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 2: {e}')
            step(f'Erro ao preencher campo 2: {str(e)[:100]}')

        # Campo 3: Endereço Atualizado - Parte Contrária
        try:
            step('Preenchendo campo 3 (Endereço).')
            # Procurar pelo input de texto com aria-label contendo "Endereço"
            field = driver.find_element(By.XPATH, "//input[@type='text' and contains(@aria-label, 'Endereço')]")
            field.clear()
            field.send_keys(payload['enderecoFinalConfirmado'])
            step('Campo 3 preenchido com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 3: {e}')
            step(f'Erro ao preencher campo 3: {str(e)[:100]}')

        # Campo 4: Minuta própria Stefanini (radio button)
        try:
            step('Preenchendo campo 4 (Minuta própria Stefanini).')
            # Procurar pelo radio button com label contendo o tipo de minuta
            radio = driver.find_element(By.XPATH, f"//input[@type='radio' and contains(@aria-label, '{payload['tipoMinuta']}')]")
            radio.click()
            step('Campo 4 preenchido com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 4: {e}')
            step(f'Erro ao preencher campo 4: {str(e)[:100]}')

        # Campo 5: Número contrato Salesforce
        try:
            step('Preenchendo campo 5 (Número Contrato Salesforce).')
            # Procurar pelo input de texto com aria-label contendo "Sales Force"
            field = driver.find_element(By.XPATH, "//input[@type='text' and contains(@aria-label, 'Sales Force')]")
            field.clear()
            field.send_keys(payload['numeroContratoSalesforce'])
            step('Campo 5 preenchido com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 5: {e}')
            step(f'Erro ao preencher campo 5: {str(e)[:100]}')

        # Campo 6: Data assinatura
        try:
            step('Preenchendo campo 6 (Data assinatura).')
            # Procurar pelo input de data
            field = driver.find_element(By.XPATH, "//input[@type='date']")
            field.clear()
            field.send_keys(payload['dataAssinaturaContratoOriginal'])
            step('Campo 6 preenchido com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 6: {e}')
            step(f'Erro ao preencher campo 6: {str(e)[:100]}')

        # Campo 7: Aditivos anteriores (file upload)
        try:
            step('Upload campo 7 (Aditivos anteriores).')
            if payload.get('arquivosAditivosAnteriores'):
                file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                if len(file_inputs) > 0:
                    file_inputs[0].send_keys(payload['arquivosAditivosAnteriores'])
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
                file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                if len(file_inputs) > 1:
                    file_inputs[1].send_keys(payload['arquivosContratoOriginal'])
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
                file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                if len(file_inputs) > 2:
                    file_inputs[2].send_keys(payload['arquivosMinutaCliente'])
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
            # Procurar pelo radio button com label contendo "Sim" ou "Não"
            radio = driver.find_element(By.XPATH, f"//input[@type='radio' and contains(@aria-label, '{reajuste_value}')]")
            radio.click()
            step(f'Campo 10 preenchido com "{reajuste_value}" com sucesso.')
        except Exception as e:
            logger.error(f'[AutoToca] Erro ao preencher campo 10: {e}')
            step(f'Erro ao preencher campo 10: {str(e)[:100]}')

        # Se houver reajuste, preencher campos 11 e 12
        if payload.get('haveraReajusteValores') == 'Sim':
            try:
                step('Campo 11 (Índice de reajuste).')
                if payload.get('indiceReajuste'):
                    # Procurar pela textarea
                    field = driver.find_element(By.XPATH, "//textarea")
                    field.clear()
                    field.send_keys(payload['indiceReajuste'])
                    step('Campo 11 preenchido com sucesso.')
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao preencher campo 11: {e}')
                step(f'Erro ao preencher campo 11: {str(e)[:100]}')
            
            try:
                step('Campo 12 (Aprovação do CEO).')
                if payload.get('arquivosAprovacaoCEO'):
                    file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                    if len(file_inputs) > 3:
                        file_inputs[3].send_keys(payload['arquivosAprovacaoCEO'])
                        step('Campo 12 preenchido com sucesso.')
                    else:
                        step('Aviso: Campo de upload 12 não encontrado.')
                else:
                    step('Campo 12: Nenhum arquivo fornecido.')
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao fazer upload campo 12: {e}')
                step(f'Erro ao fazer upload campo 12: {str(e)[:100]}')

        # Tirar screenshot do formulário preenchido
        try:
            driver.save_screenshot(str(screenshots_dir / '02-form-filled.png'))
        except:
            pass

        if submit:
            try:
                step('submit=true: enviando formulário.')
                submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Enviar')]")
                submit_btn.click()
                time.sleep(2)
                driver.save_screenshot(str(screenshots_dir / '03-form-submitted.png'))
                step('Formulário enviado com sucesso.')
            except Exception as e:
                logger.error(f'[AutoToca] Erro ao enviar formulário: {e}')
                step(f'Erro ao enviar formulário: {str(e)[:100]}')
        else:
            step('submit=false: formulário preenchido sem envio automático.')
            step('Aguardando ação do usuário (janela permanecerá aberta)...')

    except Exception as e:
        logger.exception(f'[AutoToca] Erro geral na automação: {e}')
        step(f'Erro geral: {str(e)[:200]}')
    finally:
        # Não fechar o driver se headful (deixar a janela aberta)
        if not headful and driver:
            try:
                driver.quit()
            except:
                pass
        
        # Limpar o diretório temporário se foi criado
        if temp_profile_dir and os.path.exists(temp_profile_dir):
            try:
                shutil.rmtree(temp_profile_dir)
            except:
                pass

    (screenshots_dir / 'execution-log.json').write_text(
        json.dumps({'created_at': datetime.now().isoformat(), 'steps': execution_log}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    return execution_log
