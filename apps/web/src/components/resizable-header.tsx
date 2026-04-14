"use client";

import { useState, useEffect, useRef } from "react";

interface ResizableHeaderProps {
    width: number;
    minWidth?: number;
    onResize: (width: number) => void;
    children: React.ReactNode;
    className?: string;
}

export default function ResizableHeader({
    width,
    minWidth = 50,
    onResize,
    children,
    className = "",
}: ResizableHeaderProps) {
    const [isResizing, setIsResizing] = useState(false);
    const startXRef = useRef(0);
    const startWidthRef = useRef(0);

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isResizing) return;
            const diff = e.clientX - startXRef.current;
            const newWidth = Math.max(minWidth, startWidthRef.current + diff);
            onResize(newWidth);
        };

        const handleMouseUp = () => {
            setIsResizing(false);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        };

        if (isResizing) {
            document.addEventListener("mousemove", handleMouseMove);
            document.addEventListener("mouseup", handleMouseUp);
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
        }

        return () => {
            document.removeEventListener("mousemove", handleMouseMove);
            document.removeEventListener("mouseup", handleMouseUp);
        };
    }, [isResizing, minWidth, onResize]);

    const handleMouseDown = (e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);
        startXRef.current = e.clientX;
        startWidthRef.current = width;
    };

    return (
        <th
            style={{ width }}
            className={`relative group ${className}`}
        >
            <div className="flex items-center h-full w-full">
                {children}
            </div>
            <div
                onMouseDown={handleMouseDown}
                className={`absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-indigo-500/50 ${isResizing ? "bg-indigo-500" : "bg-transparent"}`}
            />
        </th>
    );
}
