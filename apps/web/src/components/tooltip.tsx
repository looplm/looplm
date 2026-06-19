"use client";

import { useState, useRef } from "react";
import { createPortal } from "react-dom";

interface TooltipProps {
    content: React.ReactNode;
    children: React.ReactNode;
}

const MAX_W = 320; // preferred tooltip width (px)

export default function Tooltip({ content, children }: TooltipProps) {
    const [visible, setVisible] = useState(false);
    const [coords, setCoords] = useState({ left: 0, top: 0, maxWidth: MAX_W });
    const triggerRef = useRef<HTMLSpanElement>(null);

    const handleMouseEnter = () => {
        if (triggerRef.current) {
            const rect = triggerRef.current.getBoundingClientRect();
            const vw = window.innerWidth;
            // Cap width to the viewport, then clamp left so the box stays fully on-screen.
            // Without this, a trigger near the right edge leaves too little room and the box
            // shrink-to-fits into a one-word-per-line sliver.
            const maxWidth = Math.min(MAX_W, vw - 16);
            let left = rect.left + window.scrollX;
            left = Math.min(left, window.scrollX + vw - maxWidth - 8);
            left = Math.max(left, window.scrollX + 8);
            setCoords({ left, top: rect.bottom + window.scrollY + 5, maxWidth });
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
                        maxWidth: coords.maxWidth,
                        zIndex: 9999,
                    }}
                    className="p-3 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded shadow-xl text-xs text-gray-700 dark:text-slate-200 leading-relaxed whitespace-pre-wrap break-words"
                >
                    {content}
                </div>,
                document.body
            )}
        </>
    );
}
