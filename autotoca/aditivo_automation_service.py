import json
import logging
from datetime import datetime
from pathlib import Path


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

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=not headful)
        context = browser.new_context()
        page = context.new_page()

        step('Abrindo formulário externo.')
        page.goto(form_url, wait_until='domcontentloaded', timeout=120000)
        page.screenshot(path=str(screenshots_dir / '01-form-open.png'), full_page=True)

        if page.get_by_text('Entrar').count() > 0 or page.get_by_text('Sign in').count() > 0:
            step('Login corporativo/MFA detectado. Aguardando continuidade manual por até 5 minutos.')
            page.pause()

        form = _resolve_form_context(page)

        # Campos via label / role robustos
        step('Preenchendo campo 1 (Empresa Stefanini).')
        page.get_by_role('combobox', name='Empresa do grupo Stefanini').select_option(label=payload['empresaGrupoStefanini'])

        step('Preenchendo campo 2 (Razão social).')
        page.get_by_label('Razão Social - Parte Contrária').fill(payload['contaSelecionada'])

        step('Preenchendo campo 3 (Endereço).')
        page.get_by_label('Endereço Atualizado - Parte Contrária').fill(payload['enderecoFinalConfirmado'])

        step('Preenchendo campo 4 (Minuta própria).')
        page.get_by_role('radio', name=payload['tipoMinuta']).check()

        step('Preenchendo campo 5 (Contrato Salesforce).')
        page.get_by_label('Há número de contrato criado no Sales Force? Se sim, informar.').fill(payload['numeroContratoSalesforce'])

        step('Preenchendo campo 6 (Data assinatura).')
        page.get_by_label('Data de assinatura do Contrato original').fill(payload['dataAssinaturaContratoOriginal'])

        step('Upload campo 7 (Aditivos anteriores).')
        if payload.get('arquivosAditivosAnteriores'):
            page.get_by_label('Enviar cópia de todos os aditivos anteriores assinados por ambas partes').set_input_files(payload['arquivosAditivosAnteriores'])

        step('Upload campo 8 (Contrato original).')
        page.get_by_label('Enviar cópia do Contrato original assinado por ambas partes').set_input_files(payload['arquivosContratoOriginal'])

        step('Campo 9 (Minuta para validação).')
        page.get_by_role('radio', name=payload['clienteEncaminhouMinuta']).check()
        page.get_by_label('Cliente encaminhou minuta para validação? Se sim, encaminhar documento').set_input_files(payload['arquivosMinutaCliente'])

        step('Campo 10 (Reajuste de valores).')
        page.get_by_role('radio', name=payload['haveraReajusteValores']).check()

        page.screenshot(path=str(screenshots_dir / '02-form-filled.png'), full_page=True)

        if submit:
            step('submit=true: enviando formulário.')
            page.get_by_role('button', name='Enviar').click()
            page.screenshot(path=str(screenshots_dir / '03-form-submitted.png'), full_page=True)
        else:
            step('submit=false: formulário preenchido sem envio automático.')

        context.close()
        browser.close()

    (screenshots_dir / 'execution-log.json').write_text(
        json.dumps({'created_at': datetime.now().isoformat(), 'steps': execution_log}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    return execution_log
