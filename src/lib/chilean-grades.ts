export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function round(value: number, decimals = 1): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

/**
 * Escala bifásica estándar chilena:
 *  0%  → 1.0
 * 60%  → 4.0  (corte de aprobación)
 * 100% → 7.0
 *
 * Tramo bajo  (0–60%):   nota = 1 + (3 × p / 60)
 * Tramo alto (60–100%):  nota = 4 + (3 × (p − 60) / 40)
 */
export function percentageToChileanGrade(
  percentage: number,
  decimals = 1,
): number {
  const p = clamp(percentage, 0, 100);
  const grade = p <= 60 ? 1 + (3 * p) / 60 : 4 + (3 * (p - 60)) / 40;
  return round(grade, decimals);
}

export function chileanGradeToPercentage(grade: number, decimals = 0): number {
  const g = clamp(grade, 1, 7);
  // Inversa bifásica
  const percentage = g <= 4 ? ((g - 1) / 3) * 60 : 60 + ((g - 4) / 3) * 40;
  return round(percentage, decimals);
}

export function pointsToChileanGrade(
  points: number,
  total: number,
  decimals = 1,
): number {
  if (!Number.isFinite(points) || !Number.isFinite(total) || total <= 0) {
    return NaN;
  }
  return percentageToChileanGrade((points / total) * 100, decimals);
}

export function gradeLabel(grade: number): string {
  const v = clamp(grade, 1, 7);
  if (v < 2) return "Muy deficiente";
  if (v < 3) return "Deficiente";
  if (v < 4) return "Insuficiente";
  if (v < 5) return "Suficiente";
  if (v < 6) return "Bien";
  if (v < 6.5) return "Muy bien";
  return "Excelente";
}

export function isPassingGrade(grade: number): boolean {
  return clamp(grade, 1, 7) >= 4.0;
}

export function gradeFormula(percentage: number): string {
  const p = clamp(percentage, 0, 100);
  if (p <= 60) {
    return `1 + (3 × ${p.toFixed(1)} / 60) = ${percentageToChileanGrade(p).toFixed(1)}`;
  }
  return `4 + (3 × (${p.toFixed(1)} − 60) / 40) = ${percentageToChileanGrade(p).toFixed(1)}`;
}
