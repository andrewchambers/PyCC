import sys


def isAsmStr(s):
    if s.startswith("#asm"):
        return True
    if "return" in s:
        return False
    return True

def getAsmFunc(fname,templstr):
    return """
def {0}(instr):
    args = instr.assigned + instr.read
    return {1}.format(*args)
""".format(fname,templstr)


if __name__ == '__main__':
    data = eval(open(sys.argv[1]).read())
    print("# do not edit! file automatically generated by {0} {1}".format(sys.argv[0],sys.argv[1]))
    header = data.get('header',"")
    print header
    templates = data['templates']
    
    funcCounter = 0
    functions = {}
    for templ in templates:
        funcCounter += 1
        fname = "f%d"%funcCounter
        functions[templ] = fname
        if isAsmStr(templ[1]):
            print getAsmFunc(fname,templ[1])
        else:
            raise Exception("XXX")
    
    print "templtab = {"
    for templ in templates:
        print('    "{0}" : {1},'.format(templ[0],functions[templ]))
    print "}"