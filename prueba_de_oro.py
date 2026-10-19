import sys
import os
from engine.core.orchestrator import Orchestrator
from engine.adapters.instagram_adapter import InstagramAdapter

def ejecutar_prueba_de_oro():
    print("==================================================")
    print("🏆 PRUEBA DE ORO EN VIVO - INSTAGRAM (FAROL AL DÍA)")
    print("==================================================")

    # Enlace proporcionado
    url_objetivo = "https://www.instagram.com/reel/DVWnEEdEo0L/?vrfl=MWpzeGVwanQ0Nnh3aA=="
    
    # Extraer el Shortcode del Reel (DVWnEEdEo0L)
    shortcode = url_objetivo.split("/reel/")[1].split("/")[0].split("?")[0]
    comentario_real = "¡Información en tiempo real desde el corazón de la acción! 🇩🇴🔥"

    print(f"🎯 Enlace Objetivo: {url_objetivo}")
    print(f"🔑 Shortcode Extraído: {shortcode}")
    print(f"💬 Comentario a enviar: '{comentario_real}'")
    print("--------------------------------------------------")

    # Ejecutar Adaptador de Instagram
    adaptador = InstagramAdapter()
    resultado = adaptador.enviar_comentario_real(shortcode, comentario_real)

    print(f"📌 Estado de Ejecución: {resultado['status']}")
    print(f"📢 Detalle: {resultado['mensaje']}")
    if "user_agent" in resultado:
        print(f"🛡️ User-Agent Móvil Empleado: {resultado['user_agent'][:60]}...")

    print("==================================================")

if __name__ == "__main__":
    ejecutar_prueba_de_oro()
