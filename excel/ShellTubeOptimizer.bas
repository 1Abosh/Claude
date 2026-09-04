Option Explicit

' ============================================================
' ShellTubeOptimizer.bas
' Line-for-line translation of optimize_shell_and_tube_cooler()
' from CIO_Part_1.ipynb. Reads bounds from the Inputs sheet,
' writes the winning design to the Optimizer sheet.
' ============================================================

Private Function MilOilCp() As Double
    MilOilCp = 1903.1
End Function

Function LMTD_CF(Th_in As Double, Th_out As Double, Tc_in As Double, Tc_out As Double) As Double
    Dim dT1 As Double, dT2 As Double
    dT1 = Th_in - Tc_out
    dT2 = Th_out - Tc_in
    If Abs(dT1 - dT2) < 0.000001 Then
        LMTD_CF = dT1
    ElseIf dT1 <= 0 Or dT2 <= 0 Then
        LMTD_CF = (dT1 + dT2) / 2
    Else
        LMTD_CF = (dT1 - dT2) / Log(dT1 / dT2)
    End If
End Function

Function CorrectionFactorFT(Th_in As Double, Th_out As Double, Tc_in As Double, Tc_out As Double) As Double
    Dim dTc As Double, dTh As Double, dThTcin As Double
    Dim R As Double, P As Double, s As Double
    Dim lan As Double, lad As Double, dtn As Double, dtd As Double
    Dim numFt As Double, denFt As Double, ft As Double

    dTc = Tc_out - Tc_in
    dTh = Th_in - Th_out
    dThTcin = Th_in - Tc_in
    R = IIf(Abs(dTc) > 0.000001, dTh / dTc, 1000000#)
    P = IIf(Abs(dThTcin) > 0.000001, dTc / dThTcin, 0#)

    ft = 1#
    If P > 0 And P < 1 And R > 0 Then
        If Abs(R - 1) < 0.000001 Then
            ft = 1#
        Else
            s = Sqr(R ^ 2 + 1)
            lan = 1 - P
            lad = 1 - P * R
            dtn = 2 - P * (R + 1 - s)
            dtd = 2 - P * (R + 1 + s)
            If lan > 0 And lad > 0 And dtn > 0 And dtd > 0 Then
                numFt = s * Log(lan / lad)
                denFt = (R - 1) * Log(dtn / dtd)
                If Abs(denFt) > 0.000000001 Then ft = numFt / denFt
            End If
        End If
    End If
    If ft < 0 Or ft > 1 Then ft = 1#
    CorrectionFactorFT = ft
End Function

' Mirrors size_shell_and_tube_cooler(): returns Area_required, Area_provided,
' dP_tube (kPa), dP_shell (kPa) for one candidate geometry.
Sub RateDesign(Th_in As Double, Th_out As Double, mDotH As Double, _
                Tc_in As Double, Tc_out As Double, cpC As Double, rhoC As Double, muC As Double, kC As Double, _
                rhoH As Double, cpH As Double, kH As Double, muH As Double, _
                Di As Double, Do_ As Double, Dshell As Double, Ltube As Double, kWall As Double, _
                Rfi As Double, Rfo As Double, pitchRatio As Double, baffleFrac As Double, roughness As Double, _
                Nt As Long, Np As Long, _
                ByRef areaReq As Double, ByRef areaProv As Double, ByRef dPtube As Double, ByRef dPshell As Double)

    Dim Q As Double, mDotC As Double, lmtdCf As Double, ft As Double, lmtd As Double
    Dim aTube As Double, NtPerPass As Double, Ac As Double, vC As Double, ReC As Double, PrC As Double, NuC As Double, hi As Double
    Dim Pt As Double, Cclear As Double, Bbaf As Double, Ah As Double, De As Double
    Dim vH As Double, ReH As Double, PrH As Double, NuH As Double, ho As Double
    Dim invU As Double, U As Double
    Dim fTube As Double, relRough As Double, Nbaf As Long, Ncross As Long, fShell As Double

    Q = mDotH * cpH * (Th_in - Th_out)
    mDotC = Q / (cpC * (Tc_out - Tc_in))

    lmtdCf = LMTD_CF(Th_in, Th_out, Tc_in, Tc_out)
    ft = CorrectionFactorFT(Th_in, Th_out, Tc_in, Tc_out)
    lmtd = ft * lmtdCf

    aTube = Application.WorksheetFunction.Pi() / 4 * Di ^ 2
    NtPerPass = Application.WorksheetFunction.Max(1, Nt / Np)
    Ac = NtPerPass * aTube
    vC = mDotC / (rhoC * Ac)
    ReC = rhoC * vC * Di / muC
    PrC = cpC * muC / kC
    If ReC < 2300 Then NuC = 3.66 Else NuC = 0.023 * ReC ^ 0.8 * PrC ^ 0.4
    hi = NuC * kC / Di

    Pt = pitchRatio * Do_
    Cclear = Pt - Do_
    Bbaf = baffleFrac * Dshell
    Ah = Dshell * Cclear * Bbaf / Pt
    De = (3.464 * Pt ^ 2 - Application.WorksheetFunction.Pi() * Do_ ^ 2) / (Application.WorksheetFunction.Pi() * Do_)
    vH = mDotH / (rhoH * Ah)
    ReH = rhoH * vH * De / muH
    PrH = cpH * muH / kH
    If ReH < 2300 Then NuH = 3.66 Else NuH = 0.023 * ReH ^ 0.8 * PrH ^ 0.3
    ho = NuH * kH / De

    invU = (1 / ho) + Rfo + (Do_ * Log(Do_ / Di) / (2 * kWall)) + (Do_ / (Di * hi)) + Rfi * (Do_ / Di)
    U = 1 / invU

    If lmtd > 0 Then areaReq = Q / (U * lmtd) Else areaReq = 1E+30
    areaProv = Nt * Application.WorksheetFunction.Pi() * Do_ * Ltube

    If ReC < 2300 Then
        fTube = 64 / ReC
    Else
        relRough = roughness / Di
        fTube = (-1.8 * Application.WorksheetFunction.Log10(((relRough / 3.7) ^ 1.11) + (6.9 / ReC))) ^ -2
    End If
    dPtube = (Np * fTube * (Ltube / Di) * (0.5 * rhoC * vC ^ 2) + Np * 2.5 * (0.5 * rhoC * vC ^ 2)) / 1000

    If Ltube > Bbaf Then Nbaf = Int(Ltube / Bbaf) - 1 Else Nbaf = 0
    Ncross = Nbaf + 1
    If ReH < 2300 Then fShell = 64 / ReH Else fShell = 0.316 * ReH ^ -0.25
    dPshell = fShell * (Dshell / De) * (0.5 * rhoH * vH ^ 2) * Ncross / 1000
End Sub

Sub RunOptimizer()
    Dim wsIn As Worksheet, wsOpt As Worksheet
    Set wsIn = ThisWorkbook.Sheets("Inputs")
    Set wsOpt = ThisWorkbook.Sheets("Optimizer")

    Dim ThIn As Double, ThOut As Double, mDotH As Double
    Dim TcIn As Double, TcOut As Double, cpC As Double, rhoC As Double, muC As Double, kC As Double
    Dim rhoH As Double, cpH As Double, kH As Double, muH As Double
    Dim kWall As Double, Rfi As Double, Rfo As Double, pitchRatio As Double, baffleFrac As Double
    Dim wallThk As Double, roughness As Double
    Dim LtMin As Double, LtMax As Double, LtStep As Double
    Dim DsMin As Double, DsMax As Double, DsStep As Double
    Dim DoMin As Double, DoMax As Double, DoStep As Double
    Dim maxDP As Double
    Dim passesRaw As String, passesArr() As String
    Dim i As Integer

    ThIn = Range("Inputs!B7").Value
    ThOut = Range("Inputs!B8").Value
    mDotH = Range("Inputs!B9").Value
    rhoH = Range("Inputs!B10").Value
    cpH = Range("Inputs!B11").Value
    kH = Range("Inputs!B12").Value
    muH = Range("Inputs!B13").Value
    TcIn = Range("Inputs!B17").Value
    TcOut = Range("Inputs!B18").Value
    cpC = Range("Inputs!B19").Value
    rhoC = Range("Inputs!B20").Value
    muC = Range("Inputs!B21").Value
    kC = Range("Inputs!B22").Value
    kWall = Range("Inputs!B26").Value
    Rfi = Range("Inputs!B27").Value
    Rfo = Range("Inputs!B28").Value
    roughness = Range("Inputs!B29").Value
    pitchRatio = Range("Inputs!B33").Value
    baffleFrac = Range("Inputs!B34").Value
    wallThk = Range("Inputs!B35").Value
    LtMin = Range("Inputs!B39").Value
    LtMax = Range("Inputs!B40").Value
    LtStep = Range("Inputs!B41").Value
    DsMin = Range("Inputs!B42").Value
    DsMax = Range("Inputs!B43").Value
    DsStep = Range("Inputs!B44").Value
    DoMin = Range("Inputs!B45").Value
    DoMax = Range("Inputs!B46").Value
    DoStep = Range("Inputs!B47").Value
    maxDP = Range("Inputs!B48").Value
    passesRaw = Range("Inputs!B49").Value
    passesArr = Split(passesRaw, ",")

    Dim bestAreaProv As Double, found As Boolean
    Dim bestDs As Double, bestDo As Double, bestL As Double, bestNp As Long, bestNt As Long
    bestAreaProv = 1E+30
    found = False

    Dim curDs As Double, curDo As Double, curDi As Double, curL As Double
    Dim pt As Double, approxMaxNt As Long
    Dim pIdx As Integer, np As Long, nt As Long
    Dim areaReq As Double, areaProv As Double, dPtube As Double, dPshell As Double

    curDs = DsMin
    Do While curDs <= DsMax + 0.0000001
        curDo = DoMin
        Do While curDo <= DoMax + 0.0000001
            curDi = curDo - 2 * wallThk
            If curDi > 0 Then
                pt = pitchRatio * curDo
                approxMaxNt = Int(0.75 * ((curDs / pt) ^ 2) * (Application.WorksheetFunction.Pi() / 2))
                If approxMaxNt < 12 Then approxMaxNt = 12

                For pIdx = LBound(passesArr) To UBound(passesArr)
                    np = CLng(Trim(passesArr(pIdx)))
                    nt = np * 2
                    Do While nt <= approxMaxNt
                        curL = LtMin
                        Do While curL <= LtMax + 0.0000001
                            RateDesign ThIn, ThOut, mDotH, TcIn, TcOut, cpC, rhoC, muC, kC, _
                                       rhoH, cpH, kH, muH, curDi, curDo, curDs, curL, kWall, _
                                       Rfi, Rfo, pitchRatio, baffleFrac, roughness, nt, np, _
                                       areaReq, areaProv, dPtube, dPshell

                            If areaProv >= areaReq And dPtube <= maxDP And dPshell <= maxDP Then
                                If areaProv < bestAreaProv Then
                                    bestAreaProv = areaProv
                                    bestDs = curDs: bestDo = curDo: bestL = curL: bestNp = np: bestNt = nt
                                    found = True
                                End If
                            End If
                            curL = curL + LtStep
                        Loop
                        nt = nt + np * 2
                    Loop
                Next pIdx
            End If
            curDo = curDo + DoStep
        Loop
        curDs = curDs + DsStep
    Loop

    If found Then
        wsOpt.Range("B8").Value = bestDs   ' opt_D_shell
        wsOpt.Range("B9").Value = bestDo   ' opt_D_outer
        wsOpt.Range("B10").Value = bestL    ' opt_L_tube
        wsOpt.Range("B11").Value = bestNp   ' opt_N_passes
        wsOpt.Range("B12").Value = bestNt   ' opt_N_t
        wsOpt.Range("B14").Value = "Optimal design found " & Format(Now, "yyyy-mm-dd hh:mm")
        wsOpt.Range("B15").Value = bestAreaProv
    Else
        wsOpt.Range("B14").Value = "No configuration met all constraints -- widen bounds or raise max dP"
    End If

    MsgBox "Optimizer finished. " & IIf(found, "Best design written to the Optimizer sheet.", "No feasible design found."), vbInformation
End Sub
