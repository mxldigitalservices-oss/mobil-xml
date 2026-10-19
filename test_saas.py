from engine.core.orchestrator import Orchestrator

def probar_saas():
    # Simulamos que un usuario externo pegó su link en tu plataforma
    enlace_cliente = "https://www.instagram.com/reel/DVWnEEdEo0L/?vrfl=MWpzeGVwanQ0Nnh3aA=="
    texto_automatico = "¡Excelente contenido, información de valor! 🔥"

    motor = Orchestrator(plataforma="Instagram")
    motor.procesar_enlace_automatico(enlace_cliente, texto_automatico)

if __name__ == "__main__":
    probar_saas()
