from flask import Flask, request, jsonify
from engine.core.orchestrator import Orchestrator

app = Flask(__name__)

@app.route('/api/v1/interact', methods=['POST'])
def procesar_interaccion():
    data = request.get_json() or {}
    url_objetivo = data.get('url')
    mensaje = data.get('mensaje', '¡Excelente contenido!')
    plataforma = data.get('plataforma', 'Instagram')

    if not url_objetivo:
        return jsonify({"status": "error", "mensaje": "Se requiere la URL del post/reel"}), 400

    motor = Orchestrator(plataforma=plataforma)
    resultado = motor.procesar_enlace_automatico(url_objetivo, mensaje)

    return jsonify(resultado), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
