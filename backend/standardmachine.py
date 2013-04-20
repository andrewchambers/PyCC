import target
import selectiondag

from vis import irvis
from vis import dagvis
from vis import interferencevis

from passes import jumpfix
from passes import blockmerge
from passes import unused
from passes import branchreplace
from passes import constantfold

import instructionselector
import interference
import registerallocator

import ir
import function

class Register(object):
    def __init__(self,name,sizes):
        self.name = name
        self.sizes = set(sizes)
    
    def canContain(self,t):
        if type(t) == type(self):
            return True
        
        if t in self.sizes:
            return True
        
        return False
    
    def __repr__(self):
        return self.name
    
    def isPhysical(self):
        return True

class StandardMachine(target.Target):
    
    
    def translateFunction(self,f,ofile):
        
        
        if self.args.show_all or self.args.show_preopt_function:
            irvis.showFunction(f)

        if self.args.iropt:
            self.doIROpt(f)
        
        if self.args.show_all or self.args.show_postopt_function:
            irvis.showFunction(f)
        
        
        self.doInstructionSelection(f)
        
        self.callingConventions(f)
        #we are no longer in ssa after this point
        
        for block in f:
            self.blockFixups(block)
        
        self.removePhiNodes(f)
        
        if self.args.show_all or self.args.show_md_function_preallocation:
            irvis.showFunction(f)
        
        
        ig = interference.InterferenceGraph(f)
        if self.args.show_all or self.args.show_interference:
            interferencevis.showInterferenceGraph(ig)
        
        self.calleeSaveRegisters(f,ig)
        
        ra = registerallocator.RegisterAllocator(self)
        ra.allocate(f,ig)
        
        f.resolveStack()
        
        if self.args.show_all or self.args.show_md_function:
            irvis.showFunction(f)
        
        
        self.prologAndEpilog(f)
        self.preEmitCleanup(f)
        
        
        #linearize the function
        
        linear = list(f)
        
        
        #swap remove branch targets that will fall through
        for idx,b in enumerate(linear):
            terminator = b[-1]
            successors = terminator.getSuccessors()
            for target in successors:
                nextIdx = idx + 1
                if nextIdx >= len(linear):
                    continue
                if target == linear[nextIdx]:
                    terminator.swapSuccessor(target,None)
            
            terminator = self.terminatorSelection(terminator)
            if terminator == None:
                del linear[idx][-1]
            else:
                linear[idx][-1] = terminator
        
        ofile.write(".text\n")
        ofile.write(".globl %s\n" % f.name)
        ofile.write("%s:\n" % f.name)
        
        for block in linear:
            ofile.write("." + block.name + ':\n')
            for instr in block:
                ofile.write("\t" + instr.asm() + '\n')
    
    def calleeSaveRegisters(self,func,ig):
        #ig interference graph
        for block in func:
            idx = 0
            while idx < len(block):
                instr = block[idx]
                if instr.isCall():
                    liveset = ig.instrToLiveness[instr] - set(instr.assigned)
                    before = []
                    after = []
                    for var in liveset:
                        #raise Exception(str(liveset))
                        #XXX this needs to be a proper size
                        #XXX also should reuse these slots
                        ss = function.StackSlot(8)
                        func.addStackSlot(ss)
                        before.append(self.getSaveRegisterInstruction(var,ss))
                        after.append(self.getLoadRegisterInstruction(var,ss))
                    
                    for newInstr in before:
                        block.insert(idx,newInstr)
                        idx += 1
                    
                    for newInstr in after:
                        block.insert(idx + 1,newInstr)
                        idx += 1
                idx += 1
    
    def dagFixups(self,dag):
        raise Exception("unimplemented")
    
    def blockFixups(self,block):
        raise Exception("unimplemented")
    
    def removePhiNodes(self,f):
        
        mappings = []
        
        for block in f:
            idx = 0
            while idx < len(block):
                instr = block[idx]
                if type(instr) == ir.Phi:
                    mappings.append( [instr.assigned[0]] + instr.read)
                    del block[idx]
                    continue
                idx += 1
                
        for block in f:
            for instr in block:
                for mapping in mappings:
                    newV = mapping[0]
                    others = mapping[1:]
                    for oldV in others:
                        instr.swapVar(oldV,newV)
        
        
        
    def preEmitCleanup(self,f):
        for block in f:
            idx = 0
            naiveMoves = [instr for instr in block if instr.isMove() and instr.read[0] == instr.assigned[0] ]
            block.removeInstructions(naiveMoves)
        
    def doIROpt(self,func):
        while True:
            #irvis.showFunction(func)
            if constantfold.ConstantFold().runOnFunction(func):
                continue
            if jumpfix.JumpFix().runOnFunction(func):
                continue
            if blockmerge.BlockMerge().runOnFunction(func):
                continue
            if unused.UnusedVars().runOnFunction(func):
                continue
            if branchreplace.BranchReplace().runOnFunction(func):
                continue
            break
    
    def callingConventions(self,func):
        #XXX need to shift pushes to the definition to
        #stop register pressure
        for block in func:
            idx = 0
            while idx < len(block):
                instr = block[idx]
                
                if type(instr) == ir.Call:
                    newCall = self.getCallInstruction(instr)
                    block[idx] = newCall
                    pushInstructions = []
                    stackChange = 0
                    for var in reversed(instr.read):
                        stackChange += 4
                        #TODO ... must be the proper size...
                        pushInstructions += self.pushArgument(var)
                    
                    for pushinstr in pushInstructions:
                        block.insert(idx,pushinstr)
                        idx += 1
                    
                    retReg = self.getReturnReg(instr.assigned[0])
                    copy = self.getCopyFromPhysicalInstruction(instr.assigned[0],retReg)
                    newCall.assigned = [retReg]
                    idx += 1
                    block.insert(idx,copy)
                    
                    if stackChange:
                        block.insert(idx,self.getStackClearingInstruction(stackChange))
                    
                idx += 1
    
    
    def doInstructionSelection(self,func):
        for b in func:
            sd = selectiondag.SelectionDag(b)
            isel = instructionselector.InstructionSelector()
            if self.args.show_all or self.args.show_selection_dag:
                dagvis.showSelDAG(sd)
            
            self.dagFixups(sd)
            
            isel.select(self,sd)
            if self.args.show_all or self.args.show_md_selection_dag:
                dagvis.showSelDAG(sd)
            newblockops = [node.instr for node in sd.ordered() if type(node.instr) != ir.Identity]
            b.opcodes = newblockops
    
    def branchSelection(self,instr):
        raise Exception("unimlpemented")
    
    def translateModule(self,m,ofile):
        
        
        for label,data in m.data:
            ofile.write(".data\n")
            ofile.write("%s:\n"%label)
            for char in data:
                ofile.write('.byte %d\n' % ord(char))
            ofile.write('\n')
        
        for f in m:
            self.translateFunction(f,ofile)
    
    def prologAndEpilog(self,func):
        
        stackSize = func.localsSize
        entry = func.entry
        
        prolog = self.getProlog(stackSize)
        
        insertCounter = 0
        for instr in prolog:
            entry.insert(0 + insertCounter,instr)
            insertCounter += 1
        
        for b in func:
            if type(b[-1]) == ir.Ret:
                epilog = self.getEpilog(stackSize)
                for instr in epilog:
                    b.insert(-1,instr)
        
    def getEpilog(self,stackSize):
        raise Exception("unimplemented")
    
    def getProlog(self,stackSize):
        raise Exception("unimplemented")
    
    def getRegisters(self):
        return []
    
    def getMatchableInstructions(self):
        raise Exception("unimplemented")
    
    def getPossibleRegisters(self,v):
        t = type(v)
        return filter(lambda x : x.canContain(t),self.getRegisters())
    
