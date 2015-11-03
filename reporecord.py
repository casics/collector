#!/usr/bin/env python3.4
#
# @file    reporecord.py
# @brief   Basic repository information record structure.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import persistent


# Enumerations for different types of information.
# .............................................................................
#
# Originally I used the Enum class introduced in Python 3.4, but found it was
# too easy to accidentally store the full objects instead of the identifiers
# for the enum values.  Later I needed a way to map strings to values, and
# finally gave up on using the Enum class in favor of this simple approach.

class EnumeratedStrings():
    '''Base class for simple string enumerations.  Subclasses need to define
    a class constant named "_name", which is a dictionary mapping integer
    values to strings.'''

    @classmethod
    def name(cls, val):
        '''Given an identifier, return the corresponding name as a string.
        Examples:
            Language.name(Language.CPLUSPLUS) => "C++"
            Language.name(43) => "C++"
        '''
        if isinstance(val, int):
            if val >= 0 and val < len(cls._name):
                return cls._name[val]
            else:
                raise ValueError('Unknown language identifier {}'.format(val))
        else:
            raise ValueError('Expected an integer but got "{}"'.format(val))


    @classmethod
    def identifier(cls, val):
        '''Given a string, return the corresponding value.
        Examples:
            Language.identifier("C++") => 43
            Language.name(43) => "C++"
            Language.name(Language.CPLUSPLUS) => "C++"
        '''
        if isinstance(val, str):
            for identifier, string in cls._name.items():
                if val == string:
                    return identifier
            raise ValueError('Unrecognized value "{}"'.format(val))
        else:
            raise ValueError('Expected a string but got "{}"'.format(val))


class Host(EnumeratedStrings):
    '''Enumeration for known repository hosting services.'''

    # Do not sort or change the numbers.  Make additions by adding to the end.
    GITHUB      = 1
    SOURCEFORGE = 2
    BITBUCKET   = 3
    CODEPLEX    = 4
    LAUNCHPAD   = 5
    GITLAB      = 6

    _name = {
              GITHUB:      'GitHub',
              SOURCEFORGE: 'SourceForge',
              BITBUCKET:   'Bitbucket',
              CODEPLEX:    'CodePlex',
              LAUNCHPAD:   'LaunchPad',
              GITLAB:      'GitLab'
            }


class Language(EnumeratedStrings):
    '''Enumeration for known programming languages.'''

    # Do not sort or change the numbers.  Make additions by adding to the end.
    ABC                    = 1
    ACTIONSCRIPT           = 2
    ADA                    = 3
    AGILENTVEE             = 4
    ALGOL                  = 5
    ALICE                  = 6
    AMPL                   = 7
    ANGELSCRIPT            = 8
    APEX                   = 9
    APL                    = 10
    APPLESCRIPT            = 11
    ARC                    = 12
    ARDUINO                = 13
    ASP                    = 14
    ASPECTJ                = 15
    ASSEMBLY               = 16
    ATLAS                  = 17
    AUGEAS                 = 18
    AUTOHOTKEY             = 19
    AUTOIT                 = 20
    AUTOLISP               = 21
    AUTOMATOR              = 22
    AVENUE                 = 23
    AWK                    = 24
    BASH                   = 25
    BASIC                  = 26
    BC                     = 27
    BCPL                   = 28
    BEANSHELL              = 29
    BETA                   = 30
    BLITZMAX               = 31
    BOO                    = 32
    BOURNESHELL            = 33
    BRO                    = 34
    C                      = 35
    CAML                   = 36
    CEYLON                 = 37
    CFML                   = 38
    CG                     = 39
    CH                     = 40
    CHEF                   = 41
    CHILL                  = 42
    CIL                    = 43
    CIL                    = 44
    CLARION                = 45
    CLEAN                  = 46
    CLIPPER                = 47
    CLOJURE                = 48
    CLU                    = 49
    COBOL                  = 50
    COBRA                  = 51
    COFFEESCRIPT           = 52
    COLDFUSION             = 53
    COMAL                  = 54
    COMEGA                 = 55
    COMMONLISP             = 56
    COQ                    = 57
    CPL                    = 58
    CPLUSPLUS              = 59
    CSHARP                 = 60
    CSHELL                 = 61
    CSS                    = 62
    CT                     = 63
    CURL                   = 64
    D                      = 65
    DART                   = 66
    DBASE                  = 67
    DCL                    = 68
    DCPU16ASM              = 69
    DELPHI                 = 70
    DIBOL                  = 71
    DYLAN                  = 72
    E                      = 73
    EC                     = 74
    ECL                    = 75
    ECMASCRIPT             = 76
    EGL                    = 77
    EIFFEL                 = 78
    ELIXIR                 = 79
    ELM                    = 80
    EMACSLISP              = 81
    EPL                    = 82
    ERLANG                 = 83
    ESCHER                 = 84
    ETOYS                  = 85
    EUCLID                 = 86
    EUPHORIA               = 87
    EXEC                   = 88
    FACTOR                 = 89
    FALCON                 = 90
    FANCY                  = 91
    FANTOM                 = 92
    FELIX                  = 93
    FORTH                  = 94
    FORTRAN                = 95
    FORTRESS               = 96
    FOURTHDIMENSION4D      = 97
    FREGE                  = 98
    FSHARP                 = 99
    GAMBAS                 = 100
    GAMS                   = 101
    GNUOCTAVE              = 102
    GO                     = 103
    GOOGLEAPPSSCRIPT       = 104
    GOSU                   = 105
    GROOVY                 = 106
    HASKELL                = 107
    HAXE                   = 108
    HERON                  = 109
    HPL                    = 110
    HTML                   = 111
    HYPERTALK              = 112
    ICON                   = 113
    IDL                    = 114
    INFORM                 = 115
    INFORMIX4GL            = 116
    INTERCAL               = 117
    IO                     = 118
    IOKE                   = 119
    J                      = 120
    JADE                   = 121
    JAVA                   = 122
    JAVAFXSCRIPT           = 123
    JAVASCRIPT             = 124
    JSCRIPT                = 125
    JSCRIPTNET             = 126
    JSHARP                 = 127
    JULIA                  = 128
    KORNSHELL              = 129
    KOTLIN                 = 130
    KSH                    = 131
    LABVIEW                = 132
    LADDERLOGIC            = 133
    LASSO                  = 134
    LATEX                  = 135
    LIMBO                  = 136
    LINGO                  = 137
    LISP                   = 138
    LIVESCRIPT             = 139
    LOGO                   = 140
    LOGTALK                = 141
    LOTUSSCRIPT            = 142
    LPC                    = 143
    LUA                    = 144
    LUCID                  = 145
    LUSTRE                 = 146
    M4                     = 147
    MAD                    = 148
    MAGIC                  = 149
    MAGIK                  = 150
    MAKEFILE               = 151
    MALBOLGE               = 152
    MANTIS                 = 153
    MAPLE                  = 154
    MATHEMATICA            = 155
    MATLAB                 = 156
    MAXMSP                 = 157
    MAXSCRIPT              = 158
    MDL                    = 159
    MEL                    = 160
    MERCURY                = 161
    MIRAH                  = 162
    MIVA                   = 163
    ML                     = 164
    MODELICA               = 165
    MODULA2                = 166
    MODULA3                = 167
    MONKEY                 = 168
    MOO                    = 169
    MOTO                   = 170
    MSDOSBATCH             = 171
    MUMPS                  = 172
    NATURAL                = 173
    NEMERLE                = 174
    NETLOGO                = 175
    NIMROD                 = 176
    NQC                    = 177
    NSIS                   = 178
    NU                     = 179
    NU                     = 180
    NXTG                   = 181
    OBERON                 = 182
    OBJECTIVEC             = 183
    OBJECTIVEJ             = 184
    OBJECTREXX             = 185
    OCAML                  = 186
    OCCAM                  = 187
    OOC                    = 188
    OPA                    = 189
    OPENCL                 = 190
    OPENEDGEABL            = 191
    OPL                    = 192
    OZ                     = 193
    PARADOX                = 194
    PARROT                 = 195
    PASCAL                 = 196
    PERL                   = 197
    PHP                    = 198
    PIKE                   = 199
    PILOT                  = 200
    PLI                    = 201
    PLIANT                 = 202
    PLSQL                  = 203
    POSTSCRIPT             = 204
    POVRAY                 = 205
    POWERBASIC             = 206
    POWERSCRIPT            = 207
    POWERSHELL             = 208
    PROCESSING             = 209
    PROLOG                 = 210
    PUPPET                 = 211
    PUREDATA               = 212
    PYTHON                 = 213
    Q                      = 214
    R                      = 215
    RACKET                 = 216
    RATFOR                 = 217
    REALBASIC              = 218
    REBOL                  = 219
    REVOLUTION             = 220
    REXX                   = 221
    RPGOS400               = 222
    RUBY                   = 223
    RUST                   = 224
    S                      = 225
    SAS                    = 226
    SATHER                 = 227
    SCALA                  = 228
    SCHEME                 = 229
    SCILAB                 = 230
    SCRATCH                = 231
    SED                    = 232
    SEED7                  = 233
    SELF                   = 234
    SHELL                  = 235
    SIGNAL                 = 236
    SIMULA                 = 237
    SIMULINK               = 238
    SLATE                  = 239
    SMALLTALK              = 240
    SMARTY                 = 241
    SPARK                  = 242
    SPLUS                  = 243
    SPSS                   = 244
    SQR                    = 245
    SQUEAK                 = 246
    SQUIRREL               = 247
    STANDARDML             = 248
    SUNEIDO                = 249
    SUPERCOLLIDER          = 250
    SWIFT                  = 251
    TACL                   = 252
    TCL                    = 253
    TEX                    = 254
    THINBASIC              = 255
    TOM                    = 256
    TRANSACTSQL            = 257
    TURING                 = 258
    TYPESCRIPT             = 259
    VALA                   = 260
    VBSCRIPT               = 261
    VERILOG                = 262
    VHDL                   = 263
    VIML                   = 264
    VISUALBASIC            = 265
    VISUALBASICNET         = 266
    VISUALFORTRAN          = 267
    VISUALFOXPRO           = 268
    WEBDNA                 = 269
    WHITESPACE             = 270
    WOLFRAMLANGUAGE        = 271
    X10                    = 272
    XBASE                  = 273
    XBASEPLUSPLUS          = 274
    XEN                    = 275
    XPL                    = 276
    XQUERY                 = 277
    XSLT                   = 278
    YACC                   = 279
    YORICK                 = 280
    ZSHELL                 = 281
    PERL6                  = 282
    GROFF                  = 283
    APACHECONF             = 284
    CUCUMBER               = 285
    LIQUID                 = 286
    NGINX                  = 287
    RAGEL                  = 288
    LOGOS                  = 289
    BISON                  = 290
    BATCHFILE              = 291
    SOURCEPAWN             = 292
    QMAKE                  = 293
    DIGITALCOMMANDLANGUAGE = 294
    XS                     = 295
    DTRACE                 = 296
    CMAKE                  = 297
    GNUPLOT                = 298
    SYSTEMVERILOG          = 299
    CUDA                   = 300
    CMAKE                  = 301
    DTRACE                 = 302
    LEX                    = 303
    LILYPOND               = 304
    THRIFT                 = 305
    DOT                    = 306
    NEWLISP                = 307
    EAGLE                  = 308
    CHUCK                  = 309
    GLSL                   = 310
    INNOSETUP              = 311
    NIX                    = 312
    PIGLATIN               = 313
    PLPGSQL                = 314
    LLVM                   = 315
    SQLPL                  = 316
    OPENEDGEABL            = 317
    REBOL                  = 318
    GAP                    = 319
    M                      = 320
    XC                     = 321
    HAXE                   = 322
    BRAINFUCK              = 323
    COMPONENTPASCAL        = 324
    UNREALSCRIPT           = 325
    OBJECTIVECPLUSPLUS     = 326
    FLUX                   = 327
    PROTOCOLBUFFER         = 328
    BLITZBASIC             = 329
    CARTOCSS               = 330
    CRYSTAL                = 331
    GAP                    = 332
    GAME                   = 333
    HANDLEBARS             = 334
    HAXE                   = 335
    QML                    = 336
    VCL                    = 337
    XML                    = 338
    OPENSCAD               = 339
    INFORM7                = 340
    SLASH                  = 341
    MASK                   = 342
    AGSSCRIPT              = 343
    ANTLR                  = 344
    BITBAKE                = 345
    CAPNPROTO              = 346
    COOL                   = 347
    DIFF                   = 348
    GETTEXTCATALOG         = 349
    ISABELLE               = 350
    JFLEX                  = 351
    MAX                    = 352
    MODULEMANAGEMENTSYSTEM = 353
    MYGHTY                 = 354
    PUREDATA               = 355
    RENDERSCRIPT           = 356
    SQL                    = 357
    SALTSTACK              = 358
    SMALI                  = 359
    ZIMPL                  = 360
    MAKO                   = 361
    NESC                   = 362
    OWL                    = 363
    AGDA                   = 364
    CLIPS                  = 365
    CIRRU                  = 366
    DCPU16ASM              = 367
    EMBERSCRIPT            = 368
    HACK                   = 369
    HY                     = 370
    KRL                    = 371
    KICAD                  = 372
    LOLCODE                = 373
    LSL                    = 374
    MOONSCRIPT             = 375
    NCL                    = 376
    PUREBASIC              = 377
    RED                    = 378
    ROUGE                  = 379
    SMT                    = 380
    SQF                    = 381
    STATA                  = 382
    TEA                    = 383
    VOLT                   = 384
    ZEPHIR                 = 385
    ABAP                   = 386
    APIBLUEPRINT           = 387
    ATS                    = 388
    ALLOY                  = 389
    BEFUNGE                = 390
    BLUESPEC               = 391
    BRIGHTSCRIPT           = 392
    CHAPEL                 = 393
    CYCRIPT                = 394
    DM                     = 395
    DOGESCRIPT             = 396
    FREEMARKER             = 397
    GDSCRIPT               = 398
    GENSHI                 = 399
    GLYPH                  = 400
    GRAMMATICALFRAMEWORK   = 401
    HCL                    = 402
    HARBOUR                = 403
    IGORPRO                = 404
    IDRIS                  = 405
    JSONIQ                 = 406
    JASMIN                 = 407
    KIT                    = 408
    LEAN                   = 409
    LOOKML                 = 410
    LOOMSCRIPT             = 411
    MOOCODE                = 412
    NETLINX                = 413
    OXYGENE                = 414
    PAWN                   = 415
    PAN                    = 416
    PAPYRUS                = 417
    PICOLISP               = 418
    POGOSCRIPT             = 419
    PROPELLERSPIN          = 420
    PURESCRIPT             = 421
    RAML                   = 422
    REALBASIC              = 423
    REDCODE                = 424
    ROBOTFRAMEWORK         = 425
    SHELLSESSION           = 426
    TXL                    = 427
    VUE                    = 428
    WEBIDL                 = 429
    XPROC                  = 430
    XOJO                   = 431
    XTEND                  = 432
    OMGROFL                = 433
    GOLO                   = 434
    MTML                   = 435

    _name = {
              ABC:                    "ABC",
              ACTIONSCRIPT:           "ActionScript",
              ADA:                    "Ada",
              AGILENTVEE:             "AgilentVEE",
              ALGOL:                  "Algol",
              ALICE:                  "Alice",
              AMPL:                   "AMPL",
              ANGELSCRIPT:            "Angelscript",
              APEX:                   "Apex",
              APL:                    "APL",
              APPLESCRIPT:            "AppleScript",
              ARC:                    "Arc",
              ARDUINO:                "Arduino",
              ASP:                    "ASP",
              ASPECTJ:                "AspectJ",
              ASSEMBLY:               "Assembly",
              ATLAS:                  "ATLAS",
              AUGEAS:                 "Augeas",
              AUTOHOTKEY:             "AutoHotkey",
              AUTOIT:                 "AutoIt",
              AUTOLISP:               "AutoLISP",
              AUTOMATOR:              "Automator",
              AVENUE:                 "Avenue",
              AWK:                    "Awk",
              BASH:                   "Bash",
              BASIC:                  "BASIC",
              BC:                     "bc",
              BCPL:                   "BCPL",
              BEANSHELL:              "BeanShell",
              BETA:                   "BETA",
              BLITZMAX:               "BlitzMax",
              BOO:                    "Boo",
              BOURNESHELL:            "BourneShell",
              BRO:                    "Bro",
              C:                      "C",
              CAML:                   "Caml",
              CEYLON:                 "Ceylon",
              CFML:                   "CFML",
              CG:                     "cg",
              CH:                     "Ch",
              CHEF:                   "Chef",
              CHILL:                  "CHILL",
              CIL:                    "CIL",
              CIL:                    "CIL",
              CLARION:                "Clarion",
              CLEAN:                  "Clean",
              CLIPPER:                "Clipper",
              CLOJURE:                "Clojure",
              CLU:                    "CLU",
              COBOL:                  "COBOL",
              COBRA:                  "Cobra",
              COFFEESCRIPT:           "CoffeeScript",
              COLDFUSION:             "ColdFusion",
              COMAL:                  "COMAL",
              COMEGA:                 "COmega",
              COMMONLISP:             "Common Lisp",
              COQ:                    "Coq",
              CPL:                    "CPL",
              CPLUSPLUS:              "C++",
              CSHARP:                 "C#",
              CSHELL:                 "CShell",
              CSS:                    "CSS",
              CT:                     "cT",
              CURL:                   "Curl",
              D:                      "D",
              DART:                   "Dart",
              DBASE:                  "dBase",
              DCL:                    "DCL",
              DCPU16ASM:              "DCPU16ASM",
              DELPHI:                 "Delphi",
              DIBOL:                  "DiBOL",
              DYLAN:                  "Dylan",
              E:                      "E",
              EC:                     "eC",
              ECL:                    "Ecl",
              ECMASCRIPT:             "ECMAScript",
              EGL:                    "EGL",
              EIFFEL:                 "Eiffel",
              ELIXIR:                 "Elixir",
              ELM:                    "Elm",
              EMACSLISP:              "Emacs Lisp",
              EPL:                    "EPL",
              ERLANG:                 "Erlang",
              ESCHER:                 "Escher",
              ETOYS:                  "Etoys",
              EUCLID:                 "Euclid",
              EUPHORIA:               "Euphoria",
              EXEC:                   "EXEC",
              FACTOR:                 "Factor",
              FALCON:                 "Falcon",
              FANCY:                  "Fancy",
              FANTOM:                 "Fantom",
              FELIX:                  "Felix",
              FORTH:                  "Forth",
              FORTRAN:                "FORTRAN",
              FORTRESS:               "Fortress",
              FOURTHDIMENSION4D:      "FourthDimension 4D",
              FREGE:                  "Frege",
              FSHARP:                 "F#",
              GAMBAS:                 "Gambas",
              GAMS:                   "GAMS",
              GNUOCTAVE:              "GNU Octave",
              GO:                     "Go",
              GOOGLEAPPSSCRIPT:       "GoogleAppsScript",
              GOSU:                   "Gosu",
              GROOVY:                 "Groovy",
              HASKELL:                "Haskell",
              HAXE:                   "haXe",
              HERON:                  "Heron",
              HPL:                    "HPL",
              HTML:                   "HTML",
              HYPERTALK:              "HyperTalk",
              ICON:                   "Icon",
              IDL:                    "IDL",
              INFORM:                 "Inform",
              INFORMIX4GL:            "Informix 4GL",
              INTERCAL:               "INTERCAL",
              IO:                     "Io",
              IOKE:                   "Ioke",
              J:                      "J",
              JADE:                   "JADE",
              JAVA:                   "Java",
              JAVAFXSCRIPT:           "JavaFXScript",
              JAVASCRIPT:             "JavaScript",
              JSCRIPT:                "JScript",
              JSCRIPTNET:             "JScript.NET",
              JSHARP:                 "J#",
              JULIA:                  "Julia",
              KORNSHELL:              "KornShell",
              KOTLIN:                 "Kotlin",
              KSH:                    "ksh",
              LABVIEW:                "LabVIEW",
              LADDERLOGIC:            "LadderLogic",
              LASSO:                  "Lasso",
              LATEX:                  "LaTeX",
              LIMBO:                  "Limbo",
              LINGO:                  "Lingo",
              LISP:                   "Lisp",
              LIVESCRIPT:             "LiveScript",
              LOGO:                   "Logo",
              LOGTALK:                "Logtalk",
              LOTUSSCRIPT:            "LotusScript",
              LPC:                    "LPC",
              LUA:                    "Lua",
              LUCID:                  "Lucid",
              LUSTRE:                 "Lustre",
              M4:                     "M4",
              MAD:                    "MAD",
              MAGIC:                  "Magic",
              MAGIK:                  "Magik",
              MAKEFILE:               "Makefile",
              MALBOLGE:               "Malbolge",
              MANTIS:                 "MANTIS",
              MAPLE:                  "Maple",
              MATHEMATICA:            "Mathematica",
              MATLAB:                 "Matlab",
              MAXMSP:                 "MaxMSP",
              MAXSCRIPT:              "MAXScript",
              MDL:                    "MDL",
              MEL:                    "MEL",
              MERCURY:                "Mercury",
              MIRAH:                  "Mirah",
              MIVA:                   "Miva",
              ML:                     "ML",
              MODELICA:               "Modelica",
              MODULA2:                "Modula-2",
              MODULA3:                "Modula-3",
              MONKEY:                 "Monkey",
              MOO:                    "MOO",
              MOTO:                   "Moto",
              MSDOSBATCH:             "MSDOSBatch",
              MUMPS:                  "MUMPS",
              NATURAL:                "NATURAL",
              NEMERLE:                "Nemerle",
              NETLOGO:                "NetLogo",
              NIMROD:                 "Nimrod",
              NQC:                    "NQC",
              NSIS:                   "NSIS",
              NU:                     "Nu",
              NU:                     "Nu",
              NXTG:                   "NXTG",
              OBERON:                 "Oberon",
              OBJECTIVEC:             "Objective-C",
              OBJECTIVEJ:             "Objective-J",
              OBJECTREXX:             "Object Rexx",
              OCAML:                  "OCaml",
              OCCAM:                  "Occam",
              OOC:                    "ooc",
              OPA:                    "Opa",
              OPENCL:                 "OpenCL",
              OPENEDGEABL:            "OpenEdgeABL",
              OPL:                    "OPL",
              OZ:                     "Oz",
              PARADOX:                "Paradox",
              PARROT:                 "Parrot",
              PASCAL:                 "Pascal",
              PERL:                   "Perl",
              PHP:                    "PHP",
              PIKE:                   "Pike",
              PILOT:                  "PILOT",
              PLI:                    "PLI",
              PLIANT:                 "Pliant",
              PLSQL:                  "PLSQL",
              POSTSCRIPT:             "PostScript",
              POVRAY:                 "POVRay",
              POWERBASIC:             "PowerBasic",
              POWERSCRIPT:            "PowerScript",
              POWERSHELL:             "PowerShell",
              PROCESSING:             "Processing",
              PROLOG:                 "Prolog",
              PUPPET:                 "Puppet",
              PUREDATA:               "PureData",
              PYTHON:                 "Python",
              Q:                      "Q",
              R:                      "R",
              RACKET:                 "Racket",
              RATFOR:                 "Ratfor",
              REALBASIC:              "REALBasic",
              REBOL:                  "REBOL",
              REVOLUTION:             "Revolution",
              REXX:                   "REXX",
              RPGOS400:               "RPGOS400",
              RUBY:                   "Ruby",
              RUST:                   "Rust",
              S:                      "S",
              SAS:                    "SAS",
              SATHER:                 "Sather",
              SCALA:                  "Scala",
              SCHEME:                 "Scheme",
              SCILAB:                 "Scilab",
              SCRATCH:                "Scratch",
              SED:                    "sed",
              SEED7:                  "Seed7",
              SELF:                   "Self",
              SHELL:                  "Shell",
              SIGNAL:                 "SIGNAL",
              SIMULA:                 "Simula",
              SIMULINK:               "Simulink",
              SLATE:                  "Slate",
              SMALLTALK:              "Smalltalk",
              SMARTY:                 "Smarty",
              SPARK:                  "SPARK",
              SPLUS:                  "SPLUS",
              SPSS:                   "SPSS",
              SQR:                    "SQR",
              SQUEAK:                 "Squeak",
              SQUIRREL:               "Squirrel",
              STANDARDML:             "Standard ML",
              SUNEIDO:                "Suneido",
              SUPERCOLLIDER:          "SuperCollider",
              SWIFT:                  "Swift",
              TACL:                   "TACL",
              TCL:                    "Tcl",
              TEX:                    "TeX",
              THINBASIC:              "thinBasic",
              TOM:                    "TOM",
              TRANSACTSQL:            "Transact-SQL",
              TURING:                 "Turing",
              TYPESCRIPT:             "TypeScript",
              VALA:                   "Vala",
              VBSCRIPT:               "VBScript",
              VERILOG:                "Verilog",
              VHDL:                   "VHDL",
              VIML:                   "VimL",
              VISUALBASIC:            "Visual Basic",
              VISUALBASICNET:         "Visual Basic.NET",
              VISUALFORTRAN:          "Visual Fortran",
              VISUALFOXPRO:           "Visual FoxPro",
              WEBDNA:                 "WebDNA",
              WHITESPACE:             "Whitespace",
              WOLFRAMLANGUAGE:        "Wolfram Language",
              X10:                    "X10",
              XBASE:                  "xBase",
              XBASEPLUSPLUS:          "XBase++",
              XEN:                    "Xen",
              XPL:                    "XPL",
              XQUERY:                 "XQuery",
              XSLT:                   "XSLT",
              YACC:                   "Yacc",
              YORICK:                 "Yorick",
              ZSHELL:                 "Zshell",
              PERL6:                  "Perl6",
              GROFF:                  "Groff",
              APACHECONF:             "ApacheConf",
              CUCUMBER:               "Cucumber",
              LIQUID:                 "Liquid",
              NGINX:                  "Nginx",
              RAGEL:                  "Ragel in Ruby Host",
              LOGOS:                  "Logos",
              BISON:                  "Bison",
              BATCHFILE:              "Batchfile",
              SOURCEPAWN:             "SourcePawn",
              QMAKE:                  "QMake",
              DIGITALCOMMANDLANGUAGE: "DIGITAL Command Language",
              XS:                     "XS",
              DTRACE:                 "DTrace",
              CMAKE:                  "CMake",
              GNUPLOT:                "Gnuplot",
              SYSTEMVERILOG:          "SystemVerilog",
              CUDA:                   "Cuda",
              CMAKE:                  "CMake",
              DTRACE:                 "DTrace",
              LEX:                    "Lex",
              LILYPOND:               "LilyPond",
              THRIFT:                 "Thrift",
              DOT:                    "DOT",
              NEWLISP:                "NewLisp",
              EAGLE:                  "Eagle",
              CHUCK:                  "ChucK",
              GLSL:                   "GLSL",
              INNOSETUP:              "Inno Setup",
              NIX:                    "Nix",
              PIGLATIN:               "PigLatin",
              PLPGSQL:                "PLpgSQL",
              LLVM:                   "LLVM",
              SQLPL:                  "SQLPL",
              OPENEDGEABL:            "OpenEdge ABL",
              REBOL:                  "Rebol",
              GAP:                    "GAP",
              M:                      "M",
              XC:                     "XC",
              HAXE:                   "Haxe",
              BRAINFUCK:              "Brainfuck",
              COMPONENTPASCAL:        "Component Pascal",
              UNREALSCRIPT:           "UnrealScript",
              OBJECTIVECPLUSPLUS:     "Objective-C++",
              FLUX:                   "FLUX",
              PROTOCOLBUFFER:         "Protocol Buffer",
              BLITZBASIC:             "BlitzBasic",
              CARTOCSS:               "CartoCSS",
              CRYSTAL:                "Crystal",
              GAP:                    "GAP",
              GAME:                   "Game Maker Language",
              HANDLEBARS:             "Handlebars",
              HAXE:                   "Haxe",
              QML:                    "QML",
              VCL:                    "VCL",
              XML:                    "XML",
              OPENSCAD:               "OpenSCAD",
              INFORM7:                "Inform 7",
              SLASH:                  "Slash",
              MASK:                   "Mask",
              AGSSCRIPT:              "AGS Script",
              ANTLR:                  "ANTLR",
              BITBAKE:                "BitBake",
              CAPNPROTO:              "Cap'n Proto",
              COOL:                   "Cool",
              DIFF:                   "Diff",
              GETTEXTCATALOG:         "Gettext Catalog",
              ISABELLE:               "Isabelle",
              JFLEX:                  "JFlex",
              MAX:                    "Max",
              MODULEMANAGEMENTSYSTEM: "Module Management System",
              MYGHTY:                 "Myghty",
              PUREDATA:               "Pure Data",
              RENDERSCRIPT:           "RenderScript",
              SQL:                    "SQL",
              SALTSTACK:              "SaltStack",
              SMALI:                  "Smali",
              ZIMPL:                  "Zimpl",
              MAKO:                   "Mako",
              NESC:                   "nesC",
              OWL:                    "Web Ontology Language",
              AGDA:                   "Agda",
              CLIPS:                  "CLIPS",
              CIRRU:                  "Cirru",
              DCPU16ASM:              "DCPU-16 ASM",
              EMBERSCRIPT:            "EmberScript",
              HACK:                   "Hack",
              HY:                     "Hy",
              KRL:                    "KRL",
              KICAD:                  "KiCad",
              LOLCODE:                "LOLCODE",
              LSL:                    "LSL",
              MOONSCRIPT:             "MoonScript",
              NCL:                    "NCL",
              PUREBASIC:              "PureBasic",
              RED:                    "Red",
              ROUGE:                  "Rouge",
              SMT:                    "SMT",
              SQF:                    "SQF",
              STATA:                  "Stata",
              TEA:                    "Tea",
              VOLT:                   "Volt",
              ZEPHIR:                 "Zephir",
              ABAP:                   "ABAP",
              APIBLUEPRINT:           "API Blueprint",
              ATS:                    "ATS",
              ALLOY:                  "Alloy",
              BEFUNGE:                "Befunge",
              BLUESPEC:               "Bluespec",
              BRIGHTSCRIPT:           "Brightscript",
              CHAPEL:                 "Chapel",
              CYCRIPT:                "Cycript",
              DM:                     "DM",
              DOGESCRIPT:             "Dogescript",
              FREEMARKER:             "FreeMarker",
              GDSCRIPT:               "GDScript",
              GENSHI:                 "Genshi",
              GLYPH:                  "Glyph",
              GRAMMATICALFRAMEWORK:   "Grammatical Framework",
              HCL:                    "HCL",
              HARBOUR:                "Harbour",
              IGORPRO:                "IGOR Pro",
              IDRIS:                  "Idris",
              JSONIQ:                 "JSONiq",
              JASMIN:                 "Jasmin",
              KIT:                    "Kit",
              LEAN:                   "Lean",
              LOOKML:                 "LookML",
              LOOMSCRIPT:             "LoomScript",
              MOOCODE:                "Moocode",
              NETLINX:                "NetLinx",
              OXYGENE:                "Oxygene",
              PAWN:                   "PAWN",
              PAN:                    "Pan",
              PAPYRUS:                "Papyrus",
              PICOLISP:               "PicoLisp",
              POGOSCRIPT:             "PogoScript",
              PROPELLERSPIN:          "Propeller Spin",
              PURESCRIPT:             "PureScript",
              RAML:                   "RAML",
              REALBASIC:              "REALbasic",
              REDCODE:                "Redcode",
              ROBOTFRAMEWORK:         "RobotFramework",
              SHELLSESSION:           "ShellSession",
              TXL:                    "TXL",
              VUE:                    "Vue",
              WEBIDL:                 "WebIDL",
              XPROC:                  "XProc",
              XOJO:                   "Xojo",
              XTEND:                  "Xtend",
              OMGROFL:                "Omgrofl",
              GOLO:                   "Golo",
              MTML:                   "MTML",
    }


# The actual repository record.
# .............................................................................

class RepoEntry(persistent.Persistent):
    '''An entry in our index database, representing a single source repository.'''

    def __init__(self, host=0, id=0, path='', description='', owner='', type='',
                 languages=None):
        self.host = host
        self.id = id
        self.path = path
        self.description = description
        self.owner = owner
        self.owner_type = type
        self.languages = languages

    def __str__(self):
        return 'GitHub #{0} = https://github.com/{1} (owner = {2} [{3}], langs = {4})'.format(
            self.id, self.path, self.owner, self.owner_type[0], self.languages)
