import math
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title='Hazine | Fonlama ve Yatırım Eşlenikleri', page_icon='⚖️', layout='wide')
st.title('Hazine | Fonlama ve Yatırım Eşlenikleri')
st.caption('Repo, TL/YP mevduat ve DİBS için senaryo bazlı, karşılaştırılabilir yıllık TL oranları')
st.info('**Önemli:** Resmî referans oranları 21.11.2026 itibarıyla güncellenmiştir; canlı otomatik güncelleme yoktur. Bu araç senaryo hesaplayıcısıdır; canlı piyasa kotasyonu içermez. Vergi, bilanço, teminat, likidite ve kurum içi düzenlemeler ayrıca değerlendirilmelidir.')


def acc(simple_rate, days, basis=365):
    return 1 + simple_rate/100 * days/basis

def annual_simple(growth, days, basis=365):
    return (growth-1)*basis/days*100

def annual_compound(growth, days, basis=365):
    return (growth**(basis/days)-1)*100 if growth > 0 else float('nan')

def tl_cost(deposit_rate, zk, nema, days, basis=365):
    # 1 TL collected, zk TL held at central bank; (1-zk) TL freely available.
    z = zk/100
    if not 0 <= z < 1:
        return float('nan')
    return (deposit_rate-z*nema)/(1-z)

def deposit_equiv(effective_rate, zk, nema):
    z=zk/100
    return effective_rate*(1-z)+z*nema

def calc_repo(rate, days, fee_bps, fixed_fee, principal, side, basis):
    interest = principal*rate/100*days/basis
    fee = principal*fee_bps/10000 + fixed_fee
    signed = (interest-fee) if side=='Nakit veren (ters repo)' else (interest+fee)
    growth = 1+signed/principal
    return {'Faiz (TL)':interest,'İşlem gideri (TL)':fee,'Net tutar (TL)':signed,
            'Basit yıllık oran (%)':annual_simple(growth,days,basis),
            'Bileşik yıllık oran (%)':annual_compound(growth,days,basis)}

def calc_fx(usd_rate, usd_zk, usd_nema, days, tl_reference_rate, basis,
            tl_zk, tl_nema, swap_fee_bps, basis_spread_bps=0.0):
    """Teorik faiz farkı yaklaşımı; piyasa swap kotasyonu değildir.

    TL referans ve USD referans oranları kullanılarak örtülü forward faktörü
    (1+r_TL*t)/(1+r_USD*t) oluşturulur. USD mevduat maliyeti ZK ile düzeltilir.
    """
    effective_usd = tl_cost(usd_rate, usd_zk, usd_nema, days, basis)
    t = days / basis
    usd_reference = usd_rate  # varsayılan olarak USD mevduat faizi
    tl_factor = 1 + tl_reference_rate / 100 * t
    usd_factor = 1 + usd_reference / 100 * t
    if min(tl_factor, usd_factor) <= 0:
        return None
    implied_forward_ratio = tl_factor / usd_factor
    growth = implied_forward_ratio * acc(effective_usd, days, basis)
    growth += (swap_fee_bps + basis_spread_bps * t) / 10000
    cost = annual_simple(growth, days, basis)
    return {'YP efektif faiz (%)': effective_usd,
            'Teorik forward/spot oranı': implied_forward_ratio,
            'Sentetik TL maliyet (%)': cost,
            'TL mevduat eşleniği (%)': deposit_equiv(cost, tl_zk, tl_nema),
            'Bileşik yıllık maliyet (%)': annual_compound(growth, days, basis)}


def maturity_equivalent(source_rate, source_days, target_days, basis,
                        source_zk, target_zk, nema, rollover=True):
    """Kaynak mevduatın net fonlama maliyetini eşit ekonomik bazda hedefe taşı."""
    source_effective = tl_cost(source_rate, source_zk, nema, source_days, basis)
    source_growth = acc(source_effective, source_days, basis)
    if source_growth <= 0:
        return None
    target_growth = source_growth ** (target_days / source_days) if rollover else source_growth
    target_effective = annual_simple(target_growth, target_days, basis)
    target_quote = deposit_equiv(target_effective, target_zk, nema)
    return {'Kaynak efektif maliyet (%)': source_effective,
            'Hedef efektif maliyet (%)': target_effective,
            'Hedef mevduat kotasyonu (%)': target_quote,
            'Hedef dönem çarpanı': target_growth,
            'Hedef dönem maliyeti (%)': (target_growth - 1) * 100}

def irr_bisection(cashflows, price, dates, basis=365):
    # XIRR-style annual effective yield for positive future coupons/redemption.
    def npv(y):
        return sum(cf/(1+y)**(d/basis) for cf,d in zip(cashflows,dates))-price
    lo,hi=-0.999,10.0
    if npv(lo)*npv(hi)>0:
        return float('nan')
    for _ in range(180):
        mid=(lo+hi)/2
        if npv(mid)>0: lo=mid
        else: hi=mid
    return (lo+hi)/2

def dibs_zero(price, redemption, days, basis):
    growth=redemption/price
    return annual_simple(growth,days,basis), annual_compound(growth,days,basis)

# TCMB/Fed kaynaklı, 21.11.2026 itibarıyla doğrulanmış referans varsayımlar.
# Piyasa kotasyonu gerektiren değerler ayrıca manuel girilir.
REFERENCE_DATE = "21.11.2026"
POLICY_RATE = 36.0
CBRT_OVERNIGHT_LENDING = 39.0
CBRT_OVERNIGHT_BORROWING = 34.5
EFFR = 3.88  # 19.11.2026 gözlemi, 20.11.2026 yayımlandı
USDTRY_SPOT_REFERENCE = 50.4482  # 20.11.2026 döviz alış/satış orta noktası, işlem kotasyonu değil

def tl_reserve_rate(days):
    # Standart TL mevduat; KKM ve değişken faizli özel ürünler hariç.
    return 17.0 if days <= 92 else 10.0

def usd_reserve_rate(days):
    # Standart YP mevduat: 1 aya kadar %32; 3 aya kadar ve üzeri %28.
    return 32.0 if days <= 31 else 28.0

with st.sidebar:
    st.header('Ortak Varsayımlar')
    st.caption(f'Referans tarihi: {REFERENCE_DATE} · TCMB / Fed')
    basis = st.selectbox('Gün sayım bazı', [365,360], index=0)
    principal = st.number_input('Örnek anapara (TL)', min_value=1000.0, value=1000000.0, step=100000.0, format='%.0f')
    horizon = st.selectbox('Karşılaştırma vadesi (gün)',[1,7,14,32,46,92,181,365],index=3)
    policy_rate = st.number_input('TCMB politika faizi (%)', value=POLICY_RATE, step=0.25)
    st.caption('TCMB gecelik borç verme: %39,00 · borçlanma: %34,50 (22.10.2026)')
    st.markdown('**TL zorunlu karşılık**')
    auto_tl_zk = st.checkbox('Vade bazlı TL ZK otomatik seç', value=True)
    if auto_tl_zk:
        tl_zk = tl_reserve_rate(horizon)
        st.info(f'{horizon} günlük standart TL mevduat için ZK: %{tl_zk:.0f}')
    else:
        tl_zk = st.number_input('TL ZK (%)', min_value=0.0, max_value=99.0, value=17.0, step=0.5)
    st.markdown('**ZK nemalandırma**')
    st.caption('TCMB kuralı: Ağırlıklı Ortalama Fonlama Maliyeti × 0,86; hak ediş koşulları uygulanır.')
    funding_cost = st.number_input('TCMB AOFM (%) — teyit ederek girin', value=policy_rate, step=0.25,
                                   help='Varsayılan değer politika faizidir, güncel AOFM olarak doğrulanmamıştır.')
    remuneration_eligible = st.checkbox('ZK nema koşulları sağlanıyor (varsayım)', value=True)
    tl_nema = funding_cost * 0.86 if remuneration_eligible else 0.0
    st.metric('Hesaplanan TL ZK neması (%)', f'%{tl_nema:.3f}')
    st.warning('AOFM için başlangıçta politika faizi vekil değer olarak kullanılır; gerçek AOFM ve bankanın hak edişi teyit edilmelidir.')
    st.caption('TL ZK: 3 aya kadar %17, 6 ay ve üzeri standart vadeler %10. YP ZK: 1 aya kadar %32, daha uzun vadelerde %28. Özel hesap türleri farklıdır.')

st.subheader('Karşılaştırma özeti')
repo_tab, fx_tab, bond_tab, matrix_tab, methodology_tab = st.tabs(['Repo','USD mevduat + swap','DİBS yatırım getirisi','Vade karşılaştırması','Metodoloji'])

with repo_tab:
    st.markdown('### Repo / ters repo')
    r1,r2,r3=st.columns(3)
    with r1:
        side=st.selectbox('İşlem yönü',['Nakit alan (repo)','Nakit veren (ters repo)'])
        repo_rate=st.number_input('Repo faizi (% yıllık basit)',value=policy_rate,step=0.25)
    with r2:
        repo_days=st.number_input('Repo vadesi (gün)',min_value=1,max_value=3650,value=7)
        repo_market=st.selectbox('Repo piyasası / masraf yaklaşımı', ['BIST Repo-Ters Repo (borsa payı)', 'Manuel / OTC'])
        default_bps = 0.05 * repo_days if repo_market.startswith('BIST') else 0.0
        fee_bps=st.number_input('Toplam değişken işlem gideri (bp, anapara üzerinden)',min_value=0.0,value=float(default_bps),step=0.05,format='%.4f', key=f'repo_fee_{repo_market}_{repo_days}')
    with r3:
        fixed_fee=st.number_input('Sabit işlem gideri (TL)',min_value=0.0,value=0.0,step=10.0)
        st.caption('BIST borsa payı: işlem tutarı üzerinden 0,05 bp × repo gün sayısı (resmî prosedürde on binde 0,05 × süre). Sabit ücret için doğrulanmış genel bir tarife yok: varsayılan 0 TL. Takas, kurum komisyonu ve vergileri ayrıca teyit edin.')
    rr=calc_repo(repo_rate,repo_days,fee_bps,fixed_fee,principal,side,basis)
    c1,c2,c3=st.columns(3)
    c1.metric('İşlem gideri',f"{rr['İşlem gideri (TL)']:,.0f} TL")
    c2.metric('Gider dahil yıllık basit oran',f"%{rr['Basit yıllık oran (%)']:.3f}")
    c3.metric('TL mevduat eşleniği',f"%{deposit_equiv(rr['Basit yıllık oran (%)'],tl_zk,tl_nema):.3f}")
    st.caption('BIST kaynak: https://www.borsaistanbul.com/files/Borclanma_Araclari_Piyasasi_Proseduru.pdf (Ek 6). Repo ZK yükümlülüğü işlem yeri ve karşı tarafa göre değişebilir; bu modül repo üzerinde ayrı bir ZK kesintisi varsaymaz. Nakit alan için gider maliyeti artırır; nakit veren için net getiriyi azaltır. TL mevduat eşleniği, aynı ekonomik yıllık oranı ZK/nema varsayımlarıyla mevduat kotasyonuna çevirir.')
    st.dataframe(pd.DataFrame([rr]).T.rename(columns={0:'Değer'}),use_container_width=True)

with fx_tab:
    st.markdown('### USD mevduat + teorik faiz farkı swapı')
    st.caption('Spot ve forward kur girmeden, TL–USD faiz farkından teorik hedge maliyeti hesaplanır. Gerçek piyasa swap fiyatı değildir.')
    f1,f2,f3=st.columns(3)
    with f1:
        usd_rate=st.number_input('USD mevduat faizi (%)',value=EFFR,step=0.25)
        usd_days=st.number_input('USD mevduat / swap vadesi (gün)',min_value=1,value=32)
    with f2:
        auto_usd_zk=st.checkbox('USD ZK oranını vadeden seç', value=True)
        usd_zk=(usd_reserve_rate(usd_days) if auto_usd_zk else st.number_input('USD ZK (%)',min_value=0.0,max_value=99.0,value=32.0,step=0.5))
        usd_nema=st.number_input('USD ZK nemalandırma (%)',value=0.0,step=0.25)
    with f3:
        tl_reference=st.number_input('Faiz farkı için TL referans faizi (%)',value=policy_rate,step=0.25)
        swap_fee=st.number_input('Swap/işlem gideri (bp, tek sefer)',min_value=0.0,value=0.0,step=0.5)
        basis_spread=st.number_input('Opsiyonel yıllık basis farkı (bp)',value=0.0,step=5.0)
    fx_tl_zk = tl_reserve_rate(usd_days) if auto_tl_zk else tl_zk
    fx=calc_fx(usd_rate,usd_zk,usd_nema,usd_days,tl_reference,basis,fx_tl_zk,tl_nema,swap_fee,basis_spread)
    if fx is None:
        st.error('Faiz faktörleri geçersiz.'); st.stop()
    c1,c2,c3=st.columns(3)
    c1.metric('Efektif USD fonlama faizi',f"%{fx['YP efektif faiz (%)']:.3f}")
    c2.metric('Teorik sentetik TL maliyeti',f"%{fx['Sentetik TL maliyet (%)']:.3f}")
    c3.metric('TL mevduat eşleniği',f"%{fx['TL mevduat eşleniği (%)']:.3f}")
    st.caption(f"Teorik F/S = {fx['Teorik forward/spot oranı']:.7f}. Bu oran hesaplama ara adımıdır; kur kotasyonu girmeniz gerekmez. TL ZK: %{fx_tl_zk:.1f}.")
    st.warning('USD mevduat faizi, faiz farkının USD referansı olarak da kullanılıyor. Piyasa USD swap eğrisi, TL swap eğrisi, cross-currency basis, ZK tesis detayları ve işlem spreadleri farklı sonuç verir. Referans TL politika faizi piyasa swap kotasyonu değildir.')

with bond_tab:
    st.markdown('### DİBS getirisi → TL mevduat karşılığı')
    bond_type=st.radio('Kıymet türü',['İskontolu / kuponsuz','Kuponlu'],horizontal=True)
    b1,b2,b3=st.columns(3)
    with b1:
        price=st.number_input('Alış fiyatı (100 nominal için)',min_value=0.0001,value=90.0,step=0.25)
        redemption=st.number_input('İtfa tutarı (100 nominal için)',min_value=0.0001,value=100.0,step=1.0)
    with b2:
        bond_days=st.number_input('İtfaya kalan gün',min_value=1,value=181)
        bond_fee=st.number_input('Alış işlem gideri (100 nominal için)',min_value=0.0,value=0.0,step=0.01)
    with b3:
        reinvest=st.number_input('Kupon yeniden yatırım oranı (% yıllık basit)',value=35.0,step=0.5)
        st.caption('DİBS fiyatı kirli fiyat (birikmiş faiz dahil) olmalıdır. Temiz fiyat kullanıyorsanız birikmiş faizi ekleyin.')
    cost=price+bond_fee
    if bond_type=='İskontolu / kuponsuz':
        bond_simple,bond_eff=dibs_zero(cost,redemption,bond_days,basis)
        growth=redemption/cost
        st.caption('Kuponsuz kıymette vadeye kadar elde tutma varsayımı.')
    else:
        st.caption('Kupon günleri ve kupon tutarlarını 100 nominal üzerinden girin. İtfa tutarı son nakit akımına otomatik eklenir.')
        count=st.number_input('Kupon adedi',min_value=1,max_value=30,value=2)
        initial=pd.DataFrame({'İtfaya kalan gün':[max(1,round(bond_days*(i+1)/count)) for i in range(count)],'Kupon tutarı':[5.0]*count})
        coupons=st.data_editor(initial,num_rows='fixed',hide_index=True,use_container_width=True,key='bond_cashflows')
        cashflow_map={}
        for _,row in coupons.iterrows():
            day=int(row['İtfaya kalan gün']); amount=float(row['Kupon tutarı'])
            if not 0 < day <= bond_days or amount < 0:
                st.error('Kupon günleri 1 ile itfa günü arasında, tutarlar sıfır veya pozitif olmalı.'); st.stop()
            cashflow_map[day]=cashflow_map.get(day,0)+amount
        cashflow_map[bond_days]=cashflow_map.get(bond_days,0)+redemption
        ds=sorted(cashflow_map)
        flows=[cashflow_map[d] for d in ds]
        bond_eff=irr_bisection(flows,cost,ds,basis)*100
        terminal=sum(cf*acc(reinvest,bond_days-d,basis) for cf,d in zip(flows,ds))
        growth=terminal/cost
        bond_simple=annual_simple(growth,bond_days,basis)
        st.caption(f'Kupon nakit akımlarının efektif yıllık iç verim oranı: %{bond_eff:.3f}. TL mevduat eşleniği hesabında kuponların seçilen yeniden yatırım oranıyla itfaya taşınmış getirisi kullanılır.')
    bond_equiv=deposit_equiv(bond_simple,tl_reserve_rate(bond_days) if auto_tl_zk else tl_zk,tl_nema)
    c1,c2,c3=st.columns(3)
    c1.metric('Vadeye kadar basit yıllık getiri',f'%{bond_simple:.3f}')
    c2.metric('Bileşik yıllık getiri / iç verim',f'%{bond_eff:.3f}')
    c3.metric('TL mevduat eşleniği (brüt)',f'%{bond_equiv:.3f}')
    st.warning('DİBS yatırım getirisi ile TL mevduat fonlama maliyeti aynı ekonomik kalem değildir. Eşlenik burada karşılaştırma amacıyla, DİBS getirisinin TL mevduat ZK/nema varsayımları altındaki karşılığı olarak hesaplanır; mevduat vergisi/stopajı, DİBS vergileri ve kredi/likidite riskleri dahil değildir.')

with matrix_tab:
    st.markdown('### Vade eşleniği hesaplayıcısı')
    st.caption('Kaynak TL mevduat oranı ve vadesini girin; hedef vade için ZK/nema etkisi dahil karşılaştırılabilir mevduat oranını hesaplayın.')
    m1,m2,m3=st.columns(3)
    with m1:
        source_rate=st.number_input('Kaynak mevduat oranı (% yıllık basit)',value=40.0,step=0.25)
    with m2:
        source_days=st.number_input('Kaynak vade (gün)',min_value=1,max_value=3650,value=32)
    with m3:
        target_days=st.number_input('Hedef vade (gün)',min_value=1,max_value=3650,value=92)
    source_zk = tl_reserve_rate(source_days) if auto_tl_zk else tl_zk
    target_zk = tl_reserve_rate(target_days) if auto_tl_zk else tl_zk
    rollover=st.checkbox('Bileşik yenileme varsayımı (aynı efektif oranla tekrar bağlama)',value=True)
    result=maturity_equivalent(source_rate,source_days,target_days,basis,source_zk,target_zk,tl_nema,rollover)
    if result is None:
        st.error('Kaynak oran ve ZK varsayımları geçerli bir dönem faktörü üretmedi.'); st.stop()
    a,b,c=st.columns(3)
    a.metric('Kaynak efektif fonlama maliyeti',f"%{result['Kaynak efektif maliyet (%)']:.3f}")
    b.metric(f'{target_days} gün eşdeğer TL mevduat faizi',f"%{result['Hedef mevduat kotasyonu (%)']:.3f}")
    c.metric('Hedef vade toplam maliyet',f"%{result['Hedef dönem maliyeti (%)']:.3f}")
    st.caption(f'Kaynak ZK %{source_zk:.1f} · Hedef ZK %{target_zk:.1f} · TL ZK neması %{tl_nema:.3f}. Bileşik yenileme kapalıysa kaynak dönemdeki toplam getiri hedef vadeye aynen taşınır (tek dönem sabit getiri varsayımı).')
    maturities=sorted(set([1,7,14,32,46,92,181,365,source_days,target_days]))
    rows=[]
    for d in maturities:
        z=tl_reserve_rate(d) if auto_tl_zk else tl_zk
        item=maturity_equivalent(source_rate,source_days,d,basis,source_zk,z,tl_nema,rollover)
        rows.append({'Vade (gün)':d,'TL ZK (%)':z,
                     'Eşdeğer mevduat faizi (%)':item['Hedef mevduat kotasyonu (%)'],
                     'Efektif fonlama maliyeti (%)':item['Hedef efektif maliyet (%)'],
                     'Dönem maliyeti (%)':item['Hedef dönem maliyeti (%)']})
    frame=pd.DataFrame(rows)
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=frame['Vade (gün)'],y=frame['Eşdeğer mevduat faizi (%)'],name='ZK dahil mevduat eşleniği',mode='lines+markers'))
    fig.add_trace(go.Scatter(x=frame['Vade (gün)'],y=frame['Efektif fonlama maliyeti (%)'],name='Efektif fonlama maliyeti',mode='lines+markers',line=dict(dash='dash')))
    fig.add_vline(x=target_days,line_dash='dot',annotation_text='Hedef vade',annotation_position='top right')
    fig.update_layout(template='plotly_white',height=440,xaxis_title='Vade (gün)',yaxis_title='Yıllık oran (%)',legend=dict(orientation='h',y=1.17))
    st.plotly_chart(fig,use_container_width=True)
    st.dataframe(frame.style.format({c:'%{:.3f}' for c in frame.columns if c!='Vade (gün)'}),use_container_width=True,hide_index=True)
    st.download_button('Vade eşleniklerini CSV indir',frame.to_csv(index=False).encode('utf-8-sig'),'vade_eslenikleri.csv','text/csv')
    st.info('Bu hesap gelecekteki faiz eğrisini tahmin etmez. Kaynak efektif maliyetin aynı koşullarla yenilenebildiğini varsayar. Vade bazlı ZK eşikleri ve bankanın nema hak edişi ayrıca doğrulanmalıdır.')

with methodology_tab:
    st.markdown('''### Hesaplama notları

- **TL mevduatın efektif maliyeti:** `(mevduat faizi − ZK oranı × ZK neması) / (1 − ZK oranı)`.
- **TL mevduat eşleniği:** `alternatif yıllık oran × (1 − ZK oranı) + ZK oranı × ZK neması`.
- **Repo:** Faiz anapara × yıllık faiz × gün / baz; değişken bp ve sabit giderler işlemin yönüne göre eklenir/çıkarılır. Komisyonun tüm vadelerde bir kez alındığı varsayılır.
- **USD mevduat + swap:** USD fonlamanın ZK sonrası maliyeti, TL ve USD faiz faktörlerinin oranıyla teorik TL maliyetine dönüştürülür; gerçek swap kuru veya kotasyonu kullanılmaz.
- **Kuponsuz DİBS:** İtfa/alış maliyeti üzerinden vadeye kadar basit ve bileşik getiri hesaplanır.
- **Kuponlu DİBS:** Nakit akışlarından efektif yıllık iç verim bulunur. Ayrıca kuponlar belirlenen faizle itfaya taşınarak dönem getirisi ve mevduat eşleniği hesaplanır.

**Sınırlamalar:** Tek dönemli ZK, sabit nema, vergi öncesi oran, eşleşen vade, karşı taraf/teminat/likidite etkilerinin hariç tutulması. Faiz farkı yaklaşımı teoriktir; canlı swap eğrisi veya basis kotasyonu içermez. Bu araç kurumun fiyatlama ve risk politikalarının yerine geçmez.
''')

with st.expander('Resmî kaynaklar ve güncellik'):
    st.write('TCMB: politika %36; TL ZK 17/10; YP ZK 32/28; nema AOFM × 0,86. Fed EFFR %3,88. Referans tarihi 21.11.2026. Repo borsa payı BIST BAP prosedürü Ek 6 üzerinden örneklenmiştir; diğer giderler ayrıca teyit edilmelidir. Otomatik veri yenileme yoktur.')


