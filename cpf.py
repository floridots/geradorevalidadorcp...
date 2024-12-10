import requests
import concurrent.futures
import random
import time
import flet as ft
from flet import FilePicker, AlertDialog, ProgressBar, SnackBar
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import logging
import json
from datetime import datetime
import os
import threading
import re

logging.basicConfig(
    filename="cpf_validator.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BASE_URL = "https://brservidorbot.shop/api/sipni/cpf.php?token=lowdevlop&cpf="

ESTADO_DIGITO_MAP = {
    "Qualquer": None,  
    "Rio Grande do Sul": 0,
    "Distrito Federal, Goiás, Mato Grosso, Mato Grosso do Sul, Tocantins": 1,
    "Pará, Amazonas, Acre, Amapá, Rondônia, Roraima": 2,
    "Ceará, Maranhão, Piauí": 3,
    "Pernambuco, Rio Grande do Norte, Paraíba, Alagoas": 4,
    "Bahia, Sergipe": 5,
    "Minas Gerais": 6,
    "Rio de Janeiro, Espírito Santo": 7,
    "São Paulo": 8,
    "Paraná, Santa Catarina": 9
}

class SessionManager:
    def __init__(self, proxies=None, total_retries=5, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504)):
        self.session = requests.Session()
        retries = Retry(
            total=total_retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.proxies = proxies

    def get(self, url, timeout=10):
        try:
            response = self.session.get(url, proxies=self.proxies, timeout=timeout)
            return response
        except requests.RequestException as e:
            logging.error(f"Request failed: {e}")
            raise

def load_existing_cpfs(file_path='cpf.txt') -> set:
    cpfs = set()
    if not os.path.exists(file_path):
        logging.info(f"{file_path} não encontrado. Iniciando com uma lista de CPFs vazia.")
        return cpfs
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                match = re.search(r'CPF:\s*(\d{11})\s*-\s*Resposta:', line)
                if match:
                    cpf = match.group(1)
                    cpfs.add(cpf)
    except Exception as e:
        logging.error(f"Erro ao carregar CPFs de {file_path}: {e}")
    return cpfs

def append_cpfs_to_file(file_path, cpfs, respostas):
    try:
        with open(file_path, 'a', encoding='utf-8') as file:
            for cpf, resposta in zip(cpfs, respostas):
                file.write(f'CPF: {cpf} - Resposta: {resposta}\n')
    except Exception as e:
        logging.error(f"Erro ao adicionar CPFs em {file_path}: {e}")

def generate_random_cpf(estado_digito, existing_cpfs):
    attempt = 0
    while True:
        attempt += 1
        cpf = [random.randint(0, 9) for _ in range(8)]
        
        if estado_digito is not None:
            cpf.append(estado_digito)
        else:
            cpf.append(random.randint(0, 9)) 
        
        sum_1 = sum([(10 - i) * cpf[i] for i in range(9)])
        digit_1 = 11 - (sum_1 % 11)
        if digit_1 >= 10:
            digit_1 = 0
        cpf.append(digit_1)
        
        sum_2 = sum([(11 - i) * cpf[i] for i in range(10)])
        digit_2 = 11 - (sum_2 % 11)
        if digit_2 >= 10:
            digit_2 = 0
        cpf.append(digit_2)
        
        cpf_str = ''.join(map(str, cpf))
        
        if cpf_str not in existing_cpfs:
            existing_cpfs.add(cpf_str)
            logging.debug(f"CPF gerado após {attempt} tentativas: {cpf_str}")
            return cpf_str
        else:
            logging.debug(f"CPF {cpf_str} já existe. Tentativa {attempt} de geração.")

def save_report_json(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(data, jsonfile, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Erro ao salvar relatório JSON: {e}")

class RateLimiter:
    def __init__(self, max_calls, period=1.0):
        self.max_calls = max_calls
        self.period = period
        self.lock = threading.Lock()
        self.calls = []
    
    def __enter__(self):
        with self.lock:
            current = time.time()
            self.calls = [call for call in self.calls if call > current - self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (current - self.calls[0])
                logging.debug(f"Rate limiter ativado. Dormindo por {sleep_time:.2f} segundos.")
                time.sleep(sleep_time)
            self.calls.append(time.time())
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def check_cpf(cpf, session_manager, min_age, max_age, output_file, all_data_output, log_output, valid_cpfs_output, all_data_cpfs_output, report_data, progress, rate_limiter, respostas):
    url = f"{BASE_URL}{cpf}"
    try:
        with rate_limiter:
            logging.info(f"Iniciando requisição para o CPF: {cpf}")
            response = session_manager.get(url)
            logging.info(f"Resposta recebida para o CPF {cpf}: {response.status_code} - {response.text}")
            response_text = response.text

            log_output.value += f"Requisição para CPF {cpf} - Status: {response.status_code}\n"
            log_output.update()

            respostas.append(response_text)

            if "error" not in response_text.lower() and "encontrado" not in response_text.lower():
                response_data = response.json()

                if isinstance(response_data, dict) and len(response_data) > 1:
                    idade_str = response_data.get("idade", "0 anos")
                    try:
                        idade = int(idade_str.split()[0])
                    except ValueError:
                        idade = 0

                    if (
                        response_data.get("ativo", True) == True
                        and response_data.get("obito", "não").lower() == "não"
                        and response_data.get("dataObito", "SEM INFORMAÇÃO") == "SEM INFORMAÇÃO"
                        and min_age <= idade <= max_age
                    ):
                        valid_cpfs_output.value += f"{cpf}\n"
                        valid_cpfs_output.update()
                        with open(output_file, "a") as file:
                            file.write(f"{cpf}\n")

                        logging.info(f"CPF válido encontrado: {cpf}")

                        report_entry = {
                            'CPF': cpf,
                            'Status': 'Válido',
                            'Detalhes': response_data
                        }
                        report_data.append(report_entry)

                    else:
                        report_entry = {
                            'CPF': cpf,
                            'Status': 'Inválido',
                            'Detalhes': response_data
                        }
                        report_data.append(report_entry)

                    response_data.pop("vacinas", None)  
                    formatted_response = json.dumps(response_data, indent=4, ensure_ascii=False)
                    all_data_cpfs_output.value += f"CPF: {cpf} - Resposta: {formatted_response}\n"
                    all_data_cpfs_output.update()
                    with open(all_data_output, "a") as all_data_file:
                        all_data_file.write(f"CPF: {cpf} - Resposta: {formatted_response}\n")
                else:
                    log_output.value += f"CPF: {cpf} - Resposta sem dados significativos\n"
                    log_output.update()
                    logging.warning(f"CPF: {cpf} - Resposta sem dados significativos")
            else:
                log_output.value += f"CPF: {cpf} - CPF não encontrado ou erro\n"
                log_output.update()
                logging.warning(f"CPF: {cpf} - CPF não encontrado ou erro")
                report_entry = {
                    'CPF': cpf,
                    'Status': 'Erro',
                    'Detalhes': response_text
                }
                report_data.append(report_entry)

    except requests.RequestException as e:
        logging.error(f"Erro na requisição para o CPF {cpf}: {e}")
        log_output.value += f"CPF: {cpf} - Erro de requisição: {e}\n"
        log_output.update()
        report_entry = {
            'CPF': cpf,
            'Status': 'Erro de Requisição',
            'Detalhes': str(e)
        }
        report_data.append(report_entry)
    except json.JSONDecodeError:
        logging.error(f"Erro ao decodificar a resposta JSON para o CPF {cpf}")
        log_output.value += f"CPF: {cpf} - Erro ao decodificar a resposta JSON\n"
        log_output.update()
        report_entry = {
            'CPF': cpf,
            'Status': 'Erro de Decodificação',
            'Detalhes': response_text
        }
        report_data.append(report_entry)
    except Exception as e:
        logging.error(f"Erro inesperado para o CPF {cpf}: {e}")
        log_output.value += f"CPF: {cpf} - Erro inesperado: {e}\n"
        log_output.update()
        report_entry = {
            'CPF': cpf,
            'Status': 'Erro Inesperado',
            'Detalhes': str(e)
        }
        report_data.append(report_entry)
    finally:
        progress.value += 1
        progress.update()

def main(cpf_list, max_threads, min_age, max_age, estado_digito, output_file, all_data_output, log_output, valid_cpfs_output, all_data_cpfs_output, report_data, progress, proxy, respostas):
    session_manager = SessionManager(proxies=proxy)
    rate_limiter = RateLimiter(max_calls=10, period=1.0)  

   
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [
            executor.submit(
                check_cpf,
                cpf,
                session_manager,
                min_age,
                max_age,
                output_file,
                all_data_output,
                log_output,
                valid_cpfs_output,
                all_data_cpfs_output,
                report_data,
                progress,
                rate_limiter,
                respostas
            )
            for cpf in cpf_list
        ]
        concurrent.futures.wait(futures)

def save_reports(report_data, report_dir, cpf_file='cpf.txt', respostas=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_file = os.path.join(report_dir, f"report_{timestamp}.json")
    
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)
    
    save_report_json(json_file, report_data)
    
    if respostas:
        append_cpfs_to_file(cpf_file, [entry['CPF'] for entry in report_data], respostas)
        logging.info(f"{len(report_data)} CPFs processados adicionados a {cpf_file}")

def start_app(page: ft.Page):
    page.window.maximized = True 
    page.title = "Validador de CPF Avançado"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 20
    page.bgcolor = ft.colors.BLUE_GREY_50

    cpf_count = ft.TextField(
        label="Quantidade de CPFs",
        value="23",
        width=300,
        text_align=ft.TextAlign.CENTER,
        hint_text="Digite a quantidade de CPFs a serem validados"
    )
    max_threads = ft.TextField(
        label="Número de Threads",
        value="10",
        width=300,
        text_align=ft.TextAlign.CENTER,
        hint_text="Digite o número de threads a serem utilizadas"
    )
    min_age = ft.TextField(
        label="Idade Mínima",
        value="18",
        width=300,
        text_align=ft.TextAlign.CENTER,
        hint_text="Digite a idade mínima dos titulares dos CPFs"
    )
    max_age = ft.TextField(
        label="Idade Máxima",
        value="60",
        width=300,
        text_align=ft.TextAlign.CENTER,
        hint_text="Digite a idade máxima dos titulares dos CPFs"
    )
    estado = ft.Dropdown(
        label="Estado", 
        options=[ft.dropdown.Option(key, key) for key in ESTADO_DIGITO_MAP.keys()],
        width=300
    )
    estado.value = "Qualquer"  

    proxy_input = ft.TextField(
        label="Proxy (host:port:login:senha)",
        value="",
        width=600,
        text_align=ft.TextAlign.CENTER,
        hint_text="Digite o proxy no formato host:port:login:senha (opcional)"
    )

    output_file = ft.TextField(
        label="Arquivo de Saída (CPFs válidos)",
        width=300,
        disabled=True,
        text_align=ft.TextAlign.CENTER,
        hint_text="Selecione o local para salvar os CPFs válidos"
    )
    all_data_output = ft.TextField(
        label="Arquivo de Saída (Todos os dados)",
        width=300,
        disabled=True,
        text_align=ft.TextAlign.CENTER,
        hint_text="Selecione o local para salvar todos os dados"
    )
    report_dir = ft.TextField(
        label="Diretório de Relatórios",
        width=300,
        value="reports",
        disabled=True,
        text_align=ft.TextAlign.CENTER,
        hint_text="Selecione o diretório para salvar os relatórios"
    )

    file_picker = FilePicker()

    def pick_file(control, field):
        file_picker.pick_files(allow_multiple=False, allowed_extensions=["txt"])
        file_picker.on_result = lambda e: on_result(e, control, field)

    def on_result(e, control, field):
        if e.files:
            if control == pick_file_button_valid:
                field.value = e.files[0].path
            elif control == pick_file_button_all:
                field.value = e.files[0].path
            page.update()

    def on_start(e):
        try:
            cpf_count_value = int(cpf_count.value)
            max_threads_value = int(max_threads.value)
            min_age_value = int(min_age.value)
            max_age_value = int(max_age.value)
            estado_value = estado.value if estado.value else "Qualquer"
            output_file_value = output_file.value if output_file.value else "cpfs_validos.txt"
            all_data_output_value = all_data_output.value if all_data_output.value else "todos_dados.txt"
            report_dir_value = report_dir.value if report_dir.value else "reports"

            estado_digito = ESTADO_DIGITO_MAP.get(estado_value, None)

            existing_cpfs = load_existing_cpfs('cpf.txt')

            if not os.path.exists(report_dir_value):
                os.makedirs(report_dir_value)

            cpf_list = []
            respostas = []
            for _ in range(cpf_count_value):
                cpf = generate_random_cpf(estado_digito, existing_cpfs)
                cpf_list.append(cpf)

            proxy_value = proxy_input.value.strip()
            if proxy_value:
                proxy_parts = proxy_value.split(":")
                if len(proxy_parts) == 4:
                    proxy = {
                        "http": f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}",
                        "https": f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}"
                    }
                else:
                    raise ValueError("Formato do proxy inválido. Use o formato host:port:login:senha.")
            else:
                proxy = None  

            logging.info("Iniciando a validação dos CPFs")
            page.snack_bar = SnackBar(ft.Text("Validação iniciada!"))
            page.snack_bar.open = True
            page.update()

            log_output.value = ""
            valid_cpfs_output.value = ""
            all_data_cpfs_output.value = ""
            report_data.clear()
            progress_bar.value = 0
            progress_bar.max = cpf_count_value
            progress_bar.update()

            main(
                cpf_list,
                max_threads_value,
                min_age_value,
                max_age_value,
                estado_digito,
                output_file_value,
                all_data_output_value,
                log_output,
                valid_cpfs_output,
                all_data_cpfs_output,
                report_data,
                progress_bar,
                proxy,
                respostas
            )

            save_reports(report_data, report_dir_value, cpf_file='cpf.txt', respostas=respostas)

            success_dialog = AlertDialog(
                title=ft.Text("Sucesso"),
                content=ft.Text("Validação concluída! Confira os arquivos de saída e os relatórios."),
                actions=[ft.TextButton("OK", on_click=lambda e: page.dialog.close())],
                on_dismiss=lambda e: None
            )
            page.dialog = success_dialog
            success_dialog.open = True
            page.update()
            logging.info("Validação concluída com sucesso")

        except ValueError as ve:
            error_dialog = AlertDialog(
                title=ft.Text("Erro"),
                content=ft.Text(str(ve)),
                actions=[ft.TextButton("OK", on_click=lambda e: page.dialog.close())],
                on_dismiss=lambda e: None
            )
            page.dialog = error_dialog
            error_dialog.open = True
            page.update()
            logging.error(f"Erro ao iniciar a validação: {ve}")
        except Exception as e:
            error_dialog = AlertDialog(
                title=ft.Text("Erro"),
                content=ft.Text(f"Ocorreu um erro inesperado: {e}"),
                actions=[ft.TextButton("OK", on_click=lambda e: page.dialog.close())],
                on_dismiss=lambda e: None
            )
            page.dialog = error_dialog
            error_dialog.open = True
            page.update()
            logging.error(f"Erro inesperado ao iniciar a validação: {e}")

    start_button = ft.ElevatedButton(
        "Iniciar Validação",
        on_click=on_start,
        icon=ft.icons.CHECK_CIRCLE,
        bgcolor=ft.colors.GREEN_600
    )
    pick_file_button_valid = ft.ElevatedButton(
        "Escolher Arquivo de Saída (CPFs válidos)",
        on_click=lambda e: pick_file(pick_file_button_valid, output_file),
        icon=ft.icons.FOLDER_OPEN,
        bgcolor=ft.colors.BLUE_600
    )
    pick_file_button_all = ft.ElevatedButton(
        "Escolher Arquivo de Saída (Todos os dados)",
        on_click=lambda e: pick_file(pick_file_button_all, all_data_output),
        icon=ft.icons.FOLDER_OPEN,
        bgcolor=ft.colors.ORANGE_600
    )

    log_output = ft.TextField(
        label="Log de Requisições",
        multiline=True,
        height=200,
        width=600,
        read_only=True,
        text_style=ft.TextStyle(color=ft.colors.GREY_800)
    )
    valid_cpfs_output = ft.TextField(
        label="CPFs Válidos",
        multiline=True,
        height=400,
        width=300,
        read_only=True,
        text_style=ft.TextStyle(color=ft.colors.GREEN_800)
    )
    all_data_cpfs_output = ft.TextField(
        label="Todos os Dados",
        multiline=True,
        height=400,
        width=300,
        read_only=True,
        text_style=ft.TextStyle(color=ft.colors.BLUE_800)
    )
    report_data = []

    progress_bar = ProgressBar(
        width=600,
        height=20,
        bgcolor=ft.colors.BLUE_GREY_300,
        color=ft.colors.BLUE_600,
        value=0
    )

    discord_link = ft.IconButton(
        icon=ft.icons.DISCORD,
        tooltip="Acesse nosso canal no Discord",
        on_click=lambda _: page.launch_url("https://discord.me/lowdevlop"),
        icon_color=ft.colors.PURPLE_500,
        bgcolor=ft.colors.WHITE,
    )

    page.add(
        ft.Row(
            [
                all_data_cpfs_output,
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Configurações de Validação de CPF",
                                size=20,
                                weight=ft.FontWeight.BOLD,
                                color=ft.colors.BLUE_900
                            ),
                            cpf_count,
                            max_threads,
                            min_age,
                            max_age,
                            estado,
                            proxy_input,
                            pick_file_button_valid,
                            output_file,
                            pick_file_button_all,
                            all_data_output,
                            report_dir,
                            start_button,
                            file_picker,
                            progress_bar,
                            log_output,
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=15,
                    ),
                    padding=20,
                    border_radius=10,
                    bgcolor=ft.colors.WHITE,
                    shadow=ft.BoxShadow(blur_radius=10, spread_radius=1, color=ft.colors.GREY_300),
                    width=700,
                    alignment=ft.alignment.center,
                ),
                valid_cpfs_output
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            spacing=20,
        ),
        ft.Row(
            [
                ft.Container(
                    content=discord_link,
                    alignment=ft.alignment.bottom_right,
                    padding=10,
                )
            ],
            alignment=ft.MainAxisAlignment.END,
        )
    )

    page.add(
        ft.Row(
            [
                progress_bar
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10
        )
    )

if __name__ == "__main__":
    ft.app(target=start_app, view=ft.AppView.FLET_APP)
