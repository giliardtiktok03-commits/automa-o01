"""Run the saved recovery queue using the MPT environment and configuration."""
from app.services.autopilot.worker import loop

if __name__ == "__main__":
    try:
        loop()
    except KeyboardInterrupt:
        pass
