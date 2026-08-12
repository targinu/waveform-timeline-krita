#!/usr/bin/env python3
"""Instala o plugin Waveform Timeline na pasta de plugins do Krita.

Copia waveform_timeline.desktop e a pasta waveform_timeline/ para dentro
de <pasta de recursos do Krita>/pykrita/. Funciona no Windows, Linux e
macOS. Depois de rodar, siga os passos impressos no final para ativar o
plugin dentro do Krita.
"""

import os
import platform
import shutil
import sys

PLUGIN_DESKTOP_FILE = "waveform_timeline.desktop"
PLUGIN_PACKAGE_DIR = "waveform_timeline"


def find_krita_resource_dir():
    system = platform.system()
    candidates = []

    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "krita"))
    elif system == "Darwin":
        home = os.path.expanduser("~")
        candidates.append(os.path.join(
            home, "Library", "Application Support", "krita"))
    else:  # Linux e afins
        home = os.path.expanduser("~")
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            candidates.append(os.path.join(xdg, "krita"))
        candidates.append(os.path.join(home, ".local", "share", "krita"))
        # Krita instalado via Flatpak
        candidates.append(os.path.join(
            home, ".var", "app", "org.kde.krita", "data", "krita"))

    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0] if candidates else None


def print_ffmpeg_hint():
    if shutil.which("ffmpeg"):
        return
    print()
    print("AVISO: nao encontrei o ffmpeg no PATH. O plugin precisa dele")
    print("pra decodificar o audio dos documentos. Instale com:")
    system = platform.system()
    if system == "Windows":
        print("  winget install Gyan.FFmpeg")
    elif system == "Darwin":
        print("  brew install ffmpeg")
    else:
        print("  sudo apt install ffmpeg     # Debian/Ubuntu")
        print("  sudo dnf install ffmpeg     # Fedora")
        print("  sudo pacman -S ffmpeg       # Arch")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    resource_dir = find_krita_resource_dir()

    if not resource_dir or not os.path.isdir(resource_dir):
        print("Nao encontrei a pasta de recursos do Krita automaticamente.")
        print("Abra o Krita e va em Configuracoes > Gerenciar Recursos >")
        print("Abrir Pasta de Recursos pra descobrir o caminho.")
        resource_dir = input("Cole o caminho aqui: ").strip().strip('"')

    if not resource_dir or not os.path.isdir(resource_dir):
        print("Pasta invalida: %r" % resource_dir)
        sys.exit(1)

    pykrita_dir = os.path.join(resource_dir, "pykrita")
    os.makedirs(pykrita_dir, exist_ok=True)

    shutil.copy2(
        os.path.join(here, PLUGIN_DESKTOP_FILE),
        os.path.join(pykrita_dir, PLUGIN_DESKTOP_FILE))

    dest_package_dir = os.path.join(pykrita_dir, PLUGIN_PACKAGE_DIR)
    if os.path.isdir(dest_package_dir):
        shutil.rmtree(dest_package_dir)
    shutil.copytree(
        os.path.join(here, PLUGIN_PACKAGE_DIR), dest_package_dir)

    print("Plugin instalado em: %s" % pykrita_dir)
    print_ffmpeg_hint()
    print()
    print("Proximos passos:")
    print("1. Feche o Krita completamente (se estiver aberto) e abra de novo.")
    print("2. Configuracoes > Configurar o Krita > Gerenciador de Plugins")
    print("   Python, marque 'Waveform Timeline' e reinicie o Krita.")
    print("3. Configuracoes > Paineis > Waveform Timeline pra exibir o painel.")


if __name__ == "__main__":
    main()
