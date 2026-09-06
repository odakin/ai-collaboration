#!/usr/bin/env python3
"""Foil for check_E-01: the check must have teeth. Feed an operator that is NOT an effect (a negative
eigenvalue) which 'beats' the Helstrom bound; the check's effect test must reject it.
Contract: rejected → print FOIL-TEETH, exit 0; accepted → FOIL-BROKEN, exit 1."""
import numpy as np

import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("chk", pathlib.Path(__file__).with_name("check_E-01.py"))
chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)

r0, r1, p = np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]) * 0.999, 0.5   # non-orthogonal pure-ish states
bound = chk.closed_form(r0, r1, p)
fake = np.array([[1.0, 0.0], [0.0, -0.6]], complex)          # "effect" with a negative eigenvalue
beats = chk.err(r0, r1, p, fake) < bound - 1e-6
rejected = not chk.is_effect(fake)
if beats and rejected:
    print(f"FOIL-TEETH: non-positive operator beats the bound ({chk.err(r0, r1, p, fake):.4f} < {bound:.4f}) and is rejected by is_effect")
    raise SystemExit(0)
print("FOIL-BROKEN: the check would accept a non-effect" if not rejected else "FOIL-BROKEN: foil did not beat the bound (foil miswritten)")
raise SystemExit(1)
