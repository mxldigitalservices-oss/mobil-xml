from engine.core.orchestrator import Orchestrator

def ejecutar_prueba():
    print("==================================================")
    print("🚀 PRUEBA DE CAMPO EN VIVO CON TU REEL - MOBIL-XML")
    print("==================================================")

    # Enlace fijado recibido de mxl
    enlace_fijado = "https://www.instagram.com/reel/DVWnEEdEo0L/?vrfl=MWpzeGVwanQ0Nnh3aA=="
    mensaje_prueba = "¡Información al instante desde la plataforma! 🇩🇴🔥"

    print(f"🔗 Enlace Fijado: {enlace_fijado}")
    print(f"💬 Comentario: '{mensaje_prueba}'")
    print("--------------------------------------------------")

    # Ejecutar el orquestador automático
    motor = Orchestrator(plataforma="Instagram")
    resultado = motor.procesar_enlace_automatico(enlace_fijado, mensaje_prueba)

    print("--------------------------------------------------")
    print(f"📌 Estado Final: {resultado['status'].upper()}")
    print("==================================================")

if __name__ == "__main__":
    ejecutar_prueba()
