/** Корректная русская форма счётчика: 1 материал, 2 материала, 5 материалов, 11 материалов. */
export function formatMaterialCount(count: number): string {
  const mod100 = Math.abs(count) % 100;
  const mod10 = mod100 % 10;
  const word = mod100 >= 11 && mod100 <= 14
    ? "материалов"
    : mod10 === 1
      ? "материал"
      : mod10 >= 2 && mod10 <= 4
        ? "материала"
        : "материалов";
  return `${count} ${word}`;
}

/** 1 день, 2 дня, 5 дней, 11 дней. */
export function formatDayCount(count: number): string {
  const mod100 = Math.abs(count) % 100;
  const mod10 = mod100 % 10;
  const word = mod100 >= 11 && mod100 <= 14 ? "дней" : mod10 === 1 ? "день" : mod10 >= 2 && mod10 <= 4 ? "дня" : "дней";
  return `${count} ${word}`;
}
