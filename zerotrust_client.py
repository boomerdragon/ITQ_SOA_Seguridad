import json
import math
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


MTLS_HEADERS = (
    ("X-SSL-Client-Verify", "Verificación del certificado"),
    ("X-SSL-Client-S-DN", "Sujeto (Subject DN)"),
    ("X-SSL-Client-SAN", "SAN / URI SPIFFE"),
    ("X-SSL-Client-I-DN", "Emisor (Issuer CA)"),
    ("X-SSL-Client-Serial", "Número de serie"),
)


class TransferenciaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cliente Zero Trust")
        self.geometry("760x760")
        self.minsize(620, 620)

        self.api_url = tk.StringVar(value="http://127.0.0.1:8000")
        self.transfer_fields = {
            "cuenta_origen": tk.StringVar(),
            "cuenta_destino": tk.StringVar(),
            "monto": tk.StringVar(),
            "moneda": tk.StringVar(value="MXN"),
            "motivo": tk.StringVar(),
        }
        self.identity_fields = {
            header: tk.StringVar() for header, _ in MTLS_HEADERS
        }

        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        ttk.Label(container, text="URL base del API").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(container, textvariable=self.api_url).grid(
            row=1, column=0, sticky="ew", pady=(4, 12)
        )

        transfer_frame = ttk.LabelFrame(
            container, text="Procesar transferencia", padding=12
        )
        transfer_frame.grid(row=2, column=0, sticky="ew")
        transfer_frame.columnconfigure(1, weight=1)

        labels = (
            ("cuenta_origen", "Cuenta de origen"),
            ("cuenta_destino", "Cuenta de destino"),
            ("monto", "Monto"),
            ("moneda", "Moneda"),
            ("motivo", "Motivo"),
        )
        for row, (field, label) in enumerate(labels):
            ttk.Label(transfer_frame, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=3
            )
            ttk.Entry(
                transfer_frame, textvariable=self.transfer_fields[field]
            ).grid(row=row, column=1, sticky="ew", pady=3)

        identity_frame = ttk.LabelFrame(
            container, text="Identidad mTLS (opcional)", padding=12
        )
        identity_frame.grid(row=3, column=0, sticky="new", pady=(12, 0))
        identity_frame.columnconfigure(1, weight=1)
        for row, (header, label) in enumerate(MTLS_HEADERS):
            ttk.Label(identity_frame, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=3
            )
            ttk.Entry(
                identity_frame, textvariable=self.identity_fields[header]
            ).grid(row=row, column=1, sticky="ew", pady=3)

        actions = ttk.Frame(container)
        actions.grid(row=4, column=0, sticky="ew", pady=12)
        self.transfer_button = ttk.Button(
            actions,
            text="Enviar transferencia",
            command=self._submit_transfer,
        )
        self.transfer_button.pack(side="left")
        self.policies_button = ttk.Button(
            actions,
            text="Consultar políticas",
            command=self._get_policies,
        )
        self.policies_button.pack(side="left", padx=(8, 0))
        self.status_label = ttk.Label(actions, text="Listo")
        self.status_label.pack(side="right")

        response_frame = ttk.LabelFrame(
            container, text="Respuesta del API", padding=8
        )
        response_frame.grid(row=5, column=0, sticky="nsew")
        response_frame.columnconfigure(0, weight=1)
        response_frame.rowconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)

        self.response_text = tk.Text(
            response_frame, wrap="word", height=12, state="disabled"
        )
        scrollbar = ttk.Scrollbar(
            response_frame, orient="vertical", command=self.response_text.yview
        )
        self.response_text.configure(yscrollcommand=scrollbar.set)
        self.response_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _submit_transfer(self):
        try:
            amount = float(self.transfer_fields["monto"].get())
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("El monto debe ser un número mayor que cero.")
        except ValueError as exc:
            messagebox.showerror("Monto inválido", str(exc), parent=self)
            return

        payload = {
            "cuenta_origen": self.transfer_fields["cuenta_origen"].get().strip(),
            "cuenta_destino": self.transfer_fields["cuenta_destino"].get().strip(),
            "monto": amount,
            "moneda": self.transfer_fields["moneda"].get().strip(),
            "motivo": self.transfer_fields["motivo"].get().strip(),
        }
        headers = {
            name: value.get().strip()
            for name, value in self.identity_fields.items()
            if value.get().strip()
        }
        self._start_request(
            "POST",
            "/v1/transferencias/procesar",
            payload,
            headers,
        )

    def _get_policies(self):
        self._start_request("GET", "/v1/opa/policies")

    def _start_request(self, method, path, payload=None, headers=None):
        base_url = self.api_url.get().strip().rstrip("/")
        try:
            parsed_url = urlsplit(base_url)
            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.netloc
                or parsed_url.query
                or parsed_url.fragment
            ):
                raise ValueError(
                    "Ingresa una URL base HTTP(S) válida, sin parámetros."
                )

            request_headers = {"Accept": "application/json"}
            request_headers.update(headers or {})
            data = None
            if payload is not None:
                data = json.dumps(payload).encode("utf-8")
                request_headers["Content-Type"] = "application/json"
            request = Request(
                f"{base_url}{path}",
                data=data,
                headers=request_headers,
                method=method,
            )
        except ValueError as exc:
            messagebox.showerror("Solicitud inválida", str(exc), parent=self)
            return

        self._set_busy(True)
        self.status_label.configure(text="Consultando...")
        threading.Thread(
            target=self._send_request, args=(request,), daemon=True
        ).start()

    def _send_request(self, request):
        try:
            with urlopen(request, timeout=15) as response:
                result = self._decode_body(response.read())
                status_code = response.status
        except HTTPError as exc:
            result = self._decode_body(exc.read())
            status_code = exc.code
        except (URLError, TimeoutError, OSError) as exc:
            self.after(0, self._show_error, str(exc))
            return

        self.after(0, self._show_response, status_code, result)

    @staticmethod
    def _decode_body(body):
        text = body.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _show_response(self, status_code, result):
        self.status_label.configure(text=f"HTTP {status_code}")
        formatted_result = json.dumps(
            result, ensure_ascii=False, indent=2
        ) if not isinstance(result, str) else result
        self._write_response(formatted_result)
        self._set_busy(False)

    def _show_error(self, error):
        self.status_label.configure(text="Error de conexión")
        self._write_response(f"No se pudo completar la solicitud:\n{error}")
        self._set_busy(False)

    def _write_response(self, text):
        self.response_text.configure(state="normal")
        self.response_text.delete("1.0", "end")
        self.response_text.insert("1.0", text)
        self.response_text.configure(state="disabled")

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.transfer_button.configure(state=state)
        self.policies_button.configure(state=state)


if __name__ == "__main__":
    TransferenciaApp().mainloop()
