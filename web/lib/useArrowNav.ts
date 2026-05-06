import { useRef } from "react";

/**
 * Linear (vertical) arrow navigation for a column of inputs.
 * Returns a ref array and a keydown handler.
 * Usage:
 *   const { refs, handleKeyDown } = useLinearArrowNav(5);
 *   <input ref={(el) => { refs.current[i] = el; }} onKeyDown={(e) => handleKeyDown(i, e)} />
 */
export function useLinearArrowNav(length: number) {
  const refs = useRef<(HTMLInputElement | null)[]>(Array(length).fill(null));

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowUp" && index > 0) {
      e.preventDefault();
      refs.current[index - 1]?.focus();
    } else if (e.key === "ArrowDown" && index < length - 1) {
      e.preventDefault();
      refs.current[index + 1]?.focus();
    } else if (e.key === "Enter") {
      e.preventDefault();
      refs.current[index]?.blur();
    }
  }

  return { refs, handleKeyDown };
}

/**
 * Grid (2D) arrow navigation for a table of inputs.
 * Returns a 2D ref array and a keydown handler.
 * Usage:
 *   const { refs, handleKeyDown } = useGridArrowNav(rows, cols);
 *   <input ref={(el) => { refs.current[r][c] = el; }} onKeyDown={(e) => handleKeyDown(r, c, e)} />
 */
export function useGridArrowNav(rows: number, cols: number) {
  const refs = useRef<(HTMLInputElement | null)[][]>(
    Array.from({ length: rows }, () => Array(cols).fill(null)),
  );

  function handleKeyDown(row: number, col: number, e: React.KeyboardEvent<HTMLInputElement>) {
    let nr = row;
    let nc = col;
    if (e.key === "ArrowUp")         nr = row - 1;
    else if (e.key === "ArrowDown")  nr = row + 1;
    else if (e.key === "ArrowLeft")  nc = col - 1;
    else if (e.key === "ArrowRight") nc = col + 1;
    else if (e.key === "Enter") {
      e.preventDefault();
      refs.current[row]?.[col]?.blur();
      return;
    } else return;

    if (nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
      e.preventDefault();
      refs.current[nr]?.[nc]?.focus();
    }
  }

  return { refs, handleKeyDown };
}
