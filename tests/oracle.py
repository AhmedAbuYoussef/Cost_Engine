"""Shared helpers: compare engine output with a workbook's values, and build
perturbed workbooks recalculated by LibreOffice (an independent formula oracle)."""

import os
import random
import shutil
import subprocess

import openpyxl

import cost_engine
import excel_io
import excel_map

REL_TOL = 1e-9


def compare(state: dict, expected: dict):
    """Returns (number of cells compared, [(cell, excel, engine), ...] mismatches)."""
    outputs = cost_engine.compute_all(state)
    compared, bad = 0, []
    for cell, value in excel_map.excel_cells(outputs, state):
        if cell not in expected:
            continue
        compared += 1
        e = expected[cell]
        if value is None or abs(value - e) > REL_TOL * max(1.0, abs(e)):
            bad.append((cell, e, value))
    return compared, bad


def soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def perturb_workbook(src: str, dst: str, seed: int) -> int:
    """Scale every numeric input of the core sheets by a random 0.85–1.15 and switch
    half of the zero inputs on, so dormant formula paths are exercised too.  P&L
    sheets are left alone: their constants are duplicated by hand across the four
    variants (MODEL_QUIRKS.md)."""
    rng = random.Random(seed)
    wb = openpyxl.load_workbook(src)
    n = 0
    for name in excel_io.CORE_SHEETS:
        if name.startswith("P&L"):
            continue
        for row in wb[name].iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue
                if name == "Fixed Cost" and c.coordinate == "D26":   # page counter
                    continue
                if v == 0:
                    if rng.random() < 0.5:
                        c.value = rng.uniform(0.01, 1.0)
                        n += 1
                else:
                    c.value = v * rng.uniform(0.85, 1.15)
                    n += 1
    ms = wb["Market Share"]
    ms["E19"] = rng.uniform(5, 20)     # EZDK rebar export (blank in the reference)
    ms["E20"] = rng.uniform(5, 20)     # EFS rebar export (blank in the reference)
    wb.save(dst)
    return n


def recalc_with_libreoffice(paths: list, out_dir: str, profile_dir: str) -> list:
    """Open each workbook in headless LibreOffice with 'always recalculate on load'
    and save it back as .xlsx; returns the recalculated paths."""
    user = os.path.join(profile_dir, "user")
    os.makedirs(user, exist_ok=True)
    with open(os.path.join(user, "registrymodifications.xcu"), "w") as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
            '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>\n'
            '</oor:items>\n')
    subprocess.run([soffice(), f"-env:UserInstallation=file://{profile_dir}", "--headless",
                    "--convert-to", "xlsx", "--outdir", out_dir, *paths],
                   check=True, capture_output=True, timeout=600)
    return [os.path.join(out_dir, os.path.basename(p)) for p in paths]
