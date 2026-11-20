import time
import json
import uuid
import hmac
import hashlib
import base64
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException, status, Header, Depends
from pydantic import BaseModel, Field, field_validator

# ==============================================================================
# 1. CONFIGURACIÓN DE AUDITORÍA SIEM (STRUCTURED JSON LOGGING)
# ==============================================================================
class SIEMJSONFormatter(logging.Formatter):
    """
    Formateador de logs en JSON estructurado para integración directa con SIEM.
    Emite una sola línea JSON por cada evento de auditoría o seguridad.

    Nota didáctica: ``signature_hash`` es un SHA-256 del evento serializado,
    no una firma digital. Por sí solo no prueba quién creó el log ni impide
    que alguien con acceso al proceso lo modifique y vuelva a calcularlo.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_object: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "N/A"),
            "client_ip": getattr(record, "client_ip", "N/A"),
            "user_id": getattr(record, "user_id", "ANONYMOUS"),
            "event_type": getattr(record, "event_type", "SYSTEM_EVENT")
        }
        
        # Si el log incluye detalles estructurados adicionales, se incorporan al JSON
        if hasattr(record, "details"):
            log_object["details"] = getattr(record, "details")
            
        # Este digest permite detectar cambios si se compara con una copia
        # confiable; no proporciona autenticidad ni no repudio por sí mismo.
        serialized_bytes = json.dumps(log_object, sort_keys=True).encode("utf-8")
        log_object["signature_hash"] = hashlib.sha256(serialized_bytes).hexdigest()
        
        return json.dumps(log_object)

# Configuración del Logger del Sistema
logger = logging.getLogger("siem_audit_logger")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(SIEMJSONFormatter())
logger.addHandler(stream_handler)

# ==============================================================================
# 2. MOTOR JWS (JSON WEB SIGNATURE - RFC 7515)
# ==============================================================================
# IMPORTANTE: esta clave fija es solo para la demostración. En producción,
# guárdala en un gestor de secretos y permite su rotación; nunca la publiques.
CLAVE_SECRETA_JWS = "SuperSecretKey_SOA_2026_Catedra_Presencial_Cryptographic_Signing_Key"

def urlsafe_b64encode(data: bytes) -> str:
    """Codifica bytes a Base64URL sin relleno '=' de acuerdo al RFC 7515."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

def urlsafe_b64decode(b64_str: str) -> bytes:
    """Decodifica cadenas Base64URL añadiendo el relleno '=' necesario."""
    padding = '=' * (4 - (len(b64_str) % 4))
    return base64.urlsafe_b64decode((b64_str + padding).encode('utf-8'))

class JWSService:
    """
    Genera y verifica JWS en Compact Serialization: Header.Payload.Signature.

    HS256 usa HMAC, una clave secreta compartida: quien verifica también puede
    firmar. No es una firma asimétrica con clave pública/privada.
    """
    @staticmethod
    def generar_jws(payload_dict: dict, secret_key: str = CLAVE_SECRETA_JWS) -> str:
        header = {"alg": "HS256", "typ": "JWS"}
        
        header_b64 = urlsafe_b64encode(json.dumps(header, sort_keys=True).encode('utf-8'))
        payload_b64 = urlsafe_b64encode(json.dumps(payload_dict, sort_keys=True).encode('utf-8'))
        
        signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
        signature = hmac.new(secret_key.encode('utf-8'), signing_input, hashlib.sha256).digest()
        signature_b64 = urlsafe_b64encode(signature)
        
        return f"{header_b64}.{payload_b64}.{signature_b64}"

    @staticmethod
    def verificar_jws(jws_token: str, secret_key: str = CLAVE_SECRETA_JWS) -> dict:
        """
        Verifica la firma y devuelve el JSON del payload.

        Este ejemplo no interpreta ni valida el header JOSE (por ejemplo, ``alg``)
        y no convierte errores de Base64/JSON en respuestas 401; en una API real
        se deben validar todas las partes y manejar tokens malformados.
        """
        partes = jws_token.strip().split('.')
        if len(partes) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="FIRMA_JWS_MALFORMADA_ESTRUCTURA_INVALIDA"
            )
            
        header_b64, payload_b64, signature_b64 = partes
        signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
        
        # Recálculo de firma para comparación de tiempo constante
        expected_sig = hmac.new(secret_key.encode('utf-8'), signing_input, hashlib.sha256).digest()
        actual_sig = urlsafe_b64decode(signature_b64)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="FIRMA_JWS_INVALIDA_CONTENIDO_ALTERADO_O_REPUDIADO"
            )
            
        payload_bytes = urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes.decode('utf-8'))

# ==============================================================================
# 3. BASE DE DATOS FICTICIA Y CONTROL DE ACCESO A OBJETOS (BOLA)
# ==============================================================================
# Datos en memoria para enseñar autorización por objeto; no es una base real.
BASE_DATOS_CUENTAS: Dict[str, dict] = {
    "CTA-1001": {"propietario_id": "usr_alberto", "saldo": 150000.00, "moneda": "MXN", "tipo": "NOMINA"},
    "CTA-1002": {"propietario_id": "usr_beatriz", "saldo": 85000.50, "moneda": "MXN", "tipo": "AHORRO"},
    "CTA-1003": {"propietario_id": "usr_alberto", "saldo": 500000.00, "moneda": "MXN", "tipo": "INVERSION"}
}

def obtener_usuario_autenticado(x_auth_user: str = Header("usr_alberto", alias="X-Auth-User")) -> str:
    """
    Simula una identidad suministrada por un gateway.

    La cabecera y su valor predeterminado se pueden falsificar; no deben usarse
    como autenticación en producción. La identidad debe validarse en el servidor.
    """
    return x_auth_user

def verificar_autorizacion_bola(cuenta_id: str, usuario_id: str):
    """
    Mitigación de OWASP API1: Broken Object Level Authorization (BOLA).
    Compara el usuario con el dueño de la cuenta en los datos de demostración.
    Esto solo es efectivo si ``usuario_id`` proviene de autenticación confiable.
    """
    cuenta = BASE_DATOS_CUENTAS.get(cuenta_id)
    if not cuenta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RECURSO_CUENTA_NO_ENCONTRADO"
        )
        
    if cuenta["propietario_id"] != usuario_id:
        # Registro de alerta de seguridad en SIEM por intento de acceso indebido (BOLA)
        logger.warning(
            f"Alerta BOLA: Usuario '{usuario_id}' intentó acceder a la cuenta '{cuenta_id}' sin autorización.",
            extra={
                "event_type": "SECURITY_VIOLATION_BOLA",
                "user_id": usuario_id,
                "details": {"cuenta_solicitada": cuenta_id, "dueno_real": cuenta["propietario_id"]}
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ACCESO_DENEGADO_NO_ES_PROPIETARIO_DEL_RECURSO"
        )
    return cuenta

# ==============================================================================
# 4. MODELOS DTO (DATOS DE ENTRADA Y SALIDA)
# ==============================================================================
class SolicitudTransferenciaDTO(BaseModel):
    cuenta_origen: str = Field(..., examples=["CTA-1001"], min_length=5, max_length=20)
    cuenta_destino: str = Field(..., examples=["CTA-1002"], min_length=5, max_length=20)
    monto: float = Field(..., gt=0.0, description="El monto debe ser estrictamente positivo")
    motivo: str = Field(..., min_length=3, max_length=100)

    @field_validator("motivo")
    @classmethod
    def sanitizar_motivo(cls, valor: str) -> str:
        """
        Filtro didáctico de cadenas; no es una defensa XSS completa.

        XSS se mitiga principalmente escapando la salida según su contexto.
        Si el texto se usara en SQL, se deben usar consultas parametrizadas,
        no una lista negra de palabras.
        """
        caracteres_prohibidos = ["<", ">", "script", "javascript:", "select", "drop", "--"]
        for elemento in caracteres_prohibidos:
            if elemento in valor.lower():
                raise ValueError(f"El motivo contiene caracteres o secuencias no permitidas: '{elemento}'")
        return valor.strip()

# ==============================================================================
# 5. INICIALIZACIÓN DE FASTAPI Y MIDDLEWARES DE SEGURIDAD Y AUDITORÍA
# ==============================================================================
# FastAPI publica la documentación interactiva en /docs cuando la aplicación
# está en ejecución (por ejemplo: ``uvicorn audit_main:app --reload``).
app = FastAPI(
    title="API de Servicios con Auditoría SIEM, Firma JWS y Protección OWASP",
    description="Implementación integral de trazabilidad estructurada, no repudio con JWS y controles OWASP",
    version="1.0.0"
)

@app.middleware("http")
async def middleware_seguridad_y_auditoria_siem(request: Request, call_next):
    """Añade correlación, auditoría de solicitudes y cabeceras HTTP de ejemplo."""
    # El middleware HTTP de Starlette forma parte del ciclo asíncrono ASGI:
    # ``call_next`` devuelve una operación que debe esperarse con ``await``.
    # Si esta función fuera ``def``, no podría esperarla y se recibiría una
    # coroutine en lugar de la respuesta HTTP (por ejemplo, sin ``status_code``).
    # Mientras ``await`` espera a la ruta, el event loop puede atender otras
    # solicitudes; ``async`` no crea por sí solo un hilo aparte.
    # 1. Propagación o generación de Trace ID de trazabilidad
    trace_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    client_ip = request.client.host if request.client else "UNKNOWN"
    user_id = request.headers.get("X-Auth-User", "ANONYMOUS")
    
    request.state.trace_id = trace_id
    start_time = time.time()
    
    # 2. Procesamiento de la petición por la ruta correspondiente
    # La demostración registra las respuestas normales. Si ``call_next`` lanza
    # una excepción, este flujo no genera el evento de finalización.
    response: Response = await call_next(request)
    
    duration_ms = round((time.time() - start_time) * 1000, 2)
    
    # 3. Registro de auditoría JSON estructurado para SIEM
    logger.info(
        f"Petición completada: {request.method} {request.url.path} -> HTTP {response.status_code}",
        extra={
            "trace_id": trace_id,
            "client_ip": client_ip,
            "user_id": user_id,
            "event_type": "HTTP_REQUEST_AUDIT",
            "details": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms
            }
        }
    )
    
    # 4. Cabeceras de ejemplo asociadas a endurecimiento de HTTP (OWASP API8).
    # HSTS es útil cuando se sirve por HTTPS; esta API local suele usar HTTP.
    response.headers["X-Correlation-ID"] = trace_id
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    return response

# ==============================================================================
# 6. ENDPOINTS PROTEGIDOS DE LA APLICACIÓN
# ==============================================================================
# Estas rutas son ``def`` porque en esta demo no esperan operaciones asíncronas:
# acceden a datos en memoria y realizan cálculos breves. FastAPI ejecuta las
# rutas síncronas en un thread pool; si se añade I/O asíncrono (p. ej. un cliente
# HTTP o de base de datos async), la ruta debe ser ``async def`` y usar ``await``.

@app.post("/v1/jws/firmar", tags=["Criptografía JWS"])
def firmar_transaccion_jws(payload: SolicitudTransferenciaDTO):
    """Firma los datos validados; en esta demo, el algoritmo simétrico es HS256."""
    jws_token = JWSService.generar_jws(payload.model_dump())
    return {
        "estado": "FIRMA_GENERADA_EXITOSAMENTE",
        "jws_token": jws_token,
        "algoritmo": "HS256",
        "estandar": "RFC 7515"
    }

@app.post("/v1/jws/verificar-y-procesar", tags=["Criptografía JWS"])
def verificar_y_procesar_jws(jws_header: str = Header(..., alias="X-JWS-Signature")):
    """
    Verifica el token recibido en ``X-JWS-Signature``.

    La respuesta simula el procesamiento: no modifica cuentas ni ejecuta una
    transferencia real.
    """
    payload_verificado = JWSService.verificar_jws(jws_header)
    return {
        "estado": "FIRMA_VALIDA_TRANSACCION_PROCESADA",
        "datos_verificados": payload_verificado,
        "timestamp_procesamiento": datetime.now(timezone.utc).isoformat()
    }

@app.get("/v1/cuentas/{cuenta_id}/saldo", tags=["Consultas Financieras (Protección BOLA)"])
def consultar_saldo_cuenta(
    cuenta_id: str,
    usuario_autenticado: str = Depends(obtener_usuario_autenticado)
):
    """
    Endpoint protegido contra vulnerabilidad BOLA (OWASP API1).
    Solo permite ver el saldo si el usuario autenticado es el verdadero dueño.
    """
    cuenta = verificar_autorizacion_bola(cuenta_id, usuario_autenticado)
    return {
        "cuenta_id": cuenta_id,
        "propietario": cuenta["propietario_id"],
        "saldo": cuenta["saldo"],
        "moneda": cuenta["moneda"],
        "tipo_cuenta": cuenta["tipo"]
    }