"use client";
import {type ReactNode} from "react";
import {Modal} from "@heroui/react";
// Original Phoenix CompetitionCenter modal composition, backed by native settings.
export function ConfigModal({open,onClose,title,children}:{open:boolean;onClose:()=>void;title:string;children:ReactNode}){
 return <Modal isOpen={open} onOpenChange={value=>{if(!value)onClose();}}><Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog><Modal.Header><Modal.Heading>{title}</Modal.Heading><Modal.CloseTrigger aria-label="关闭"/></Modal.Header><Modal.Body className="px-integration-modal">{children}</Modal.Body></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>;
}
