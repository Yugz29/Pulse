"""Pulse V0 daemon: local activity to durable daily trace.

Volontairement sans import : les outils CLI (audit, outbox) importent des
sous-modules sans Flask ; un import eager de main ici forcerait Flask pour
tout le package.
"""
