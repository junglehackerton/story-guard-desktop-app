/** Sort multi-file manuscript imports by the episode number in each filename. */
export function sortImportPaths(paths: string[]): string[] {
  return [...paths].sort((left, right) => {
    const leftName = left.split(/[\\/]/).pop() ?? left;
    const rightName = right.split(/[\\/]/).pop() ?? right;
    const leftMatch = leftName.match(/(?:^|[^0-9])(\d+)/);
    const rightMatch = rightName.match(/(?:^|[^0-9])(\d+)/);
    const leftNumber = leftMatch ? Number(leftMatch[1]) : Number.POSITIVE_INFINITY;
    const rightNumber = rightMatch ? Number(rightMatch[1]) : Number.POSITIVE_INFINITY;
    if (leftNumber !== rightNumber) return leftNumber - rightNumber;
    return leftName.localeCompare(rightName, "ko");
  });
}
