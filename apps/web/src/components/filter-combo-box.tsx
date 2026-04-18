"use client";

import { useState, useRef, useEffect, useCallback } from "react";

type FilterMode = "include" | "exclude";

interface FilterComboBoxProps {
  label: string;
  placeholder?: string;
  options: string[];
  selected: string[];
  onSelectedChange: (values: string[]) => void;
  mode: FilterMode;
  onModeChange: (mode: FilterMode) => void;
  allowFreeText?: boolean;
  hideModeToggle?: boolean;
  disabled?: boolean;
  disabledReason?: string;
}

export default function FilterComboBox({
  label,
  placeholder = "Type to filter...",
  options,
  selected,
  onSelectedChange,
  mode,
  onModeChange,
  allowFreeText = true,
  hideModeToggle = false,
  disabled = false,
  disabledReason,
}: FilterComboBoxProps) {
  const [inputValue, setInputValue] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Close dropdown on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = options.filter(
    (o) =>
      !selected.includes(o) &&
      o.toLowerCase().includes(inputValue.toLowerCase())
  );

  const addValue = useCallback(
    (val: string) => {
      if (val && !selected.includes(val)) {
        onSelectedChange([...selected, val]);
      }
      setInputValue("");
    },
    [selected, onSelectedChange]
  );

  const removeValue = useCallback(
    (val: string) => {
      onSelectedChange(selected.filter((s) => s !== val));
    },
    [selected, onSelectedChange]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && inputValue.trim() && (allowFreeText || inputValue.includes("*"))) {
      e.preventDefault();
      addValue(inputValue.trim());
    } else if (e.key === "Backspace" && !inputValue && selected.length > 0) {
      removeValue(selected[selected.length - 1]);
    } else if (e.key === "Escape") {
      setIsOpen(false);
      inputRef.current?.blur();
    }
  };

  return (
    <div className="flex flex-col gap-1" ref={containerRef}>
      <div className="flex items-center gap-2">
        <label className="text-xs text-gray-500 dark:text-slate-400 font-medium" title={disabled ? disabledReason : undefined}>
          {label}
        </label>
        {!hideModeToggle && (
          <button
            type="button"
            onClick={() => onModeChange(mode === "include" ? "exclude" : "include")}
            className={`px-1.5 py-0.5 text-[10px] font-medium rounded-full border transition-colors ${
              mode === "include"
                ? "bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 border-indigo-200 dark:border-indigo-800"
                : "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400 border-red-200 dark:border-red-800"
            }`}
          >
            {mode === "include" ? "IN" : "NOT"}
          </button>
        )}
      </div>

      <div className="relative">
        {/* Chips + input rendered inline inside a single styled container */}
        <div
          className={`flex flex-wrap items-center gap-1 px-2 py-1 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg min-w-[200px] focus-within:border-indigo-500 ${disabled ? "opacity-60 cursor-not-allowed" : "cursor-text"}`}
          title={disabled ? disabledReason : undefined}
          onClick={() => { if (!disabled) inputRef.current?.focus(); }}
        >
          {selected.map((val) => {
            const isWildcard = val.includes("*");
            return (
            <span
              key={val}
              title={val}
              className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs font-medium whitespace-nowrap max-w-[160px] ${
                mode === "include"
                  ? "bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300"
                  : "bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300"
              } ${isWildcard ? "border border-dashed border-current" : ""}`}
            >
              <span className="truncate">{val}</span>
              {!disabled && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); removeValue(val); }}
                  className="hover:opacity-70 transition-opacity flex-shrink-0 ml-0.5"
                >
                  &times;
                </button>
              )}
            </span>
            );
          })}
          <input
            ref={inputRef}
            type="text"
            placeholder={selected.length > 0 ? "" : placeholder}
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value);
              setIsOpen(true);
            }}
            onFocus={() => setIsOpen(true)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            className="flex-1 min-w-[60px] bg-transparent text-sm text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none py-0.5 disabled:cursor-not-allowed"
          />
        </div>

        {/* Dropdown */}
        {!disabled && isOpen && (filtered.length > 0 || inputValue.trim()) && (
          <div className="absolute z-50 mt-1 w-full max-h-48 overflow-auto bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg shadow-lg">
            {filtered.slice(0, 20).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => {
                  addValue(option);
                  inputRef.current?.focus();
                }}
                className="w-full text-left px-3 py-1.5 text-sm text-gray-700 dark:text-slate-200 hover:bg-indigo-50 dark:hover:bg-indigo-950 transition-colors"
              >
                {option}
              </button>
            ))}
            {inputValue.trim() &&
              !selected.includes(inputValue.trim()) &&
              (allowFreeText || inputValue.includes("*")) && (
                <button
                  type="button"
                  onClick={() => {
                    addValue(inputValue.trim());
                    inputRef.current?.focus();
                  }}
                  className="w-full text-left px-3 py-1.5 text-sm text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950 transition-colors border-t border-gray-100 dark:border-slate-700"
                >
                  {inputValue.includes("*")
                    ? <>Add wildcard &ldquo;{inputValue.trim()}&rdquo;</>
                    : <>Add &ldquo;{inputValue.trim()}&rdquo;</>}
                </button>
              )}
          </div>
        )}
      </div>
    </div>
  );
}
