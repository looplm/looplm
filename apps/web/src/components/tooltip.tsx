"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";

interface TooltipProps {
    content: React.ReactNode;
    children: React.ReactNode;
}

export default function Tooltip({ content, children }: TooltipProps) {
    const [visible, setVisible] = useState(false);
    const [coords, setCoords] = useState({ left: 0, top: 0 });
    const triggerRef = useRef<HTMLSpanElement>(null);

    const handleMouseEnter = () => {
        if (triggerRef.current) {
            const rect = triggerRef.current.getBoundingClientRect();
            setCoords({
                left: rect.left + window.scrollX,
                top: rect.bottom + window.scrollY + 5, // 5px offset
            });
            setVisible(true);
        }
    };

    const handleMouseLeave = () => {
        setVisible(false);
    };

    return (
        <>
            <span
                ref={triggerRef}
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
                className="inline-block max-w-full"
            >
                {children}
            </span>
            {visible && createPortal(
                <div
                    style={{
                        position: "absolute",
                        left: coords.left,
                        top: coords.top,
                        zIndex: 9999,
                    }}
                    className="max-w-md p-3 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded shadow-xl text-xs text-gray-700 dark:text-slate-200 whitespace-pre-wrap break-words"
                >
                    {content}
                </div>,
                document.body
            )}
        </>
    );
}
