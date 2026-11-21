import math
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title='Hazine | Fonlama ve Yatırım Eşlenikleri', page_icon='⚖️', layout='wide')
st.title('Hazine | Fonlama ve Yatırım Eşlenikleri')
st.caption('Repo, TL/YP mevduat ve DİBS için senaryo bazlı, karşılaştırılabilir yıllık TL oranları')
st.info('**Önemli:** Bu araç senaryo hesaplayıcısıdır; canlı piyasa kotasyonu içermez. Vergi, bilanço, teminat, likidite ve kurum içi düzenlemeler ayrıca değerlendirilmelidir.')


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

def calc_fx(usd_rate, usd_zk, usd_nema, days, spot, forward, basis, tl_zk, tl_nema, swap_fee_bps):
    # Borrow USD deposits; required reserves remunerated in USD. Remaining USD is swapped into TL.
    effective_usd = tl_cost(usd_rate,usd_zk,usd_nema,days,basis)
    if spot <= 0 or forward <= 0:
        return None
    # TL proceeds at spot, USD repayment at forward. Annualized simple cost for fixed horizon.
    growth = (forward/spot) * acc(effective_usd,days,basis) + swap_fee_bps/10000
    cost = annual_simple(growth,days,basis)
    return {'YP efektif faiz (%)':effective_usd,'Sentetik TL maliyet (%)':cost,
            'TL mevduat eşleniği (%)':deposit_equiv(cost,tl_zk,tl_nema),
            'Bileşik yıllık maliyet (%)':annual_compound(growth,days,basis)}

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

with st.sidebar:
    st.header('Ortak Varsayımlar')
    basis = st.selectbox('Gün sayım bazı', [365,360], index=0)
    principal = st.number_input('Örnek anapara (TL)', min_value=1000.0, value=1000000.0, step=100000.0, format='%.0f')
    horizon = st.selectbox('Karşılaştırma vadesi (gün)',[1,7,14,32,46,92,181,365],index=3)
    tl_zk = st.number_input('TL ZK (%)',min_value=0.0,max_value=99.0,value=2.5,step=0.5)
    tl_nema = st.number_input('TL ZK nemalandırma (%)',value=35.0,step=0.25)
    st.caption('ZK parametreleri örnektir. İlgili yükümlülük türü, vade ve güncel TCMB düzenlemesine göre doğrulayın.')

st.subheader('Karşılaştırma özeti')
repo_tab, fx_tab, bond_tab, matrix_tab, methodology_tab = st.tabs(['Repo','USD mevduat + swap','DİBS yatırım getirisi','Vade karşılaştırması','Metodoloji'])

with repo_tab:
    st.markdown('### Repo / ters repo')
    r1,r2,r3=st.columns(3)
    with r1:
        side=st.selectbox('İşlem yönü',['Nakit alan (repo)','Nakit veren (ters repo)'])
        repo_rate=st.number_input('Repo faizi (% yıllık basit)',value=40.0,step=0.25)
    with r2:
        repo_days=st.number_input('Repo vadesi (gün)',min_value=1,max_value=3650,value=7)
        fee_bps=st.number_input('Toplam değişken işlem gideri (bp, anapara üzerinden)',min_value=0.0,value=1.0,step=0.5)
    with r3:
        fixed_fee=st.number_input('Sabit işlem gideri (TL)',min_value=0.0,value=0.0,step=10.0)
        st.caption('Komisyon, platform ve ilgili diğer masrafları toplam olarak girin; vergi varsayımlarını ayrıca ekleyin.')
    rr=calc_repo(repo_rate,repo_days,fee_bps,fixed_fee,principal,side,basis)
    c1,c2,c3=st.columns(3)
    c1.metric('İşlem gideri',f"{rr['İşlem gideri (TL)']:,.0f} TL")
    c2.metric('Gider dahil yıllık basit oran',f"%{rr['Basit yıllık oran (%)']:.3f}")
    c3.metric('TL mevduat eşleniği',f"%{deposit_equiv(rr['Basit yıllık oran (%)'],tl_zk,tl_nema):.3f}")
    st.caption('Nakit alan için gider maliyeti artırır; nakit veren için net getiriyi azaltır. TL mevduat eşleniği, aynı ekonomik yıllık oranı ZK/nema varsayımlarıyla mevduat kotasyonuna çevirir.')
    st.dataframe(pd.DataFrame([rr]).T.rename(columns={0:'Değer'}),use_container_width=True)

with fx_tab:
    st.markdown('### USD mevduatın sentetik TL fonlama maliyeti')
    f1,f2,f3=st.columns(3)
    with f1:
        usd_rate=st.number_input('USD mevduat faizi (%)',value=4.0,step=0.25)
        usd_days=st.number_input('USD mevduat / swap vadesi (gün)',min_value=1,value=32)
    with f2:
        usd_zk=st.number_input('USD ZK (%)',min_value=0.0,max_value=99.0,value=32.0,step=0.5)
        usd_nema=st.number_input('USD ZK nemalandırma (%)',value=0.0,step=0.25)
    with f3:
        spot=st.number_input('USD/TRY spot',min_value=0.0001,value=42.0,step=0.1,format='%.4f')
        forward=st.number_input('USD/TRY forward (aynı vade)',min_value=0.0001,value=43.0,step=0.1,format='%.4f')
        swap_fee=st.number_input('Swap/işlem gideri (bp, TL anapara üzerinden)',min_value=0.0,value=0.0,step=0.5)
    fx=calc_fx(usd_rate,usd_zk,usd_nema,usd_days,spot,forward,basis,tl_zk,tl_nema,swap_fee)
    c1,c2,c3=st.columns(3)
    c1.metric('Efektif USD fonlama faizi',f"%{fx['YP efektif faiz (%)']:.3f}")
    c2.metric('Sentetik TL fonlama maliyeti',f"%{fx['Sentetik TL maliyet (%)']:.3f}")
    c3.metric('TL mevduat eşleniği',f"%{fx['TL mevduat eşleniği (%)']:.3f}")
    st.warning('Model, spot ve forward işlemlerinin aynı vade ve anapara bazında hedge edildiğini varsayar. YP ZK tesis biçimi, çapraz para swapının nakit akımları, basis ve diğer bilanço maliyetleri gerçek işlemlerde farklılaşabilir.')

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
    bond_equiv=deposit_equiv(bond_simple,tl_zk,tl_nema)
    c1,c2,c3=st.columns(3)
    c1.metric('Vadeye kadar basit yıllık getiri',f'%{bond_simple:.3f}')
    c2.metric('Bileşik yıllık getiri / iç verim',f'%{bond_eff:.3f}')
    c3.metric('TL mevduat eşleniği (brüt)',f'%{bond_equiv:.3f}')
    st.warning('DİBS yatırım getirisi ile TL mevduat fonlama maliyeti aynı ekonomik kalem değildir. Eşlenik burada karşılaştırma amacıyla, DİBS getirisinin TL mevduat ZK/nema varsayımları altındaki karşılığı olarak hesaplanır; mevduat vergisi/stopajı, DİBS vergileri ve kredi/likidite riskleri dahil değildir.')

with matrix_tab:
    st.markdown('### Vade ve bileşikleşme karşılaştırması')
    st.caption('Sabit oranla yeniden yatırım/yenileme varsayımıdır; gelecekteki faizleri tahmin etmez.')
    maturities=[1,7,14,32,46,92,181,365]
    rows=[]
    for d in maturities:
        repo_result=calc_repo(repo_rate,d,fee_bps,fixed_fee,principal,side,basis)
        r=repo_result['Basit yıllık oran (%)']
        rows.append({'Vade (gün)':d,'Repo gider dahil (%)':r,'Repo TL mevduat eşleniği (%)':deposit_equiv(r,tl_zk,tl_nema),
                     'TL mevduat teklif (%)':deposit_equiv(repo_rate,tl_zk,tl_nema),
                     'Repo efektif yıllık (%)':repo_result['Bileşik yıllık oran (%)']})
    frame=pd.DataFrame(rows)
    st.dataframe(frame.style.format({c:'%{:.3f}' for c in frame.columns if c!='Vade (gün)'}),use_container_width=True,hide_index=True)
    fig=go.Figure()
    for col in ['Repo gider dahil (%)','Repo TL mevduat eşleniği (%)','Repo efektif yıllık (%)']:
        fig.add_trace(go.Scatter(x=frame['Vade (gün)'],y=frame[col],name=col,mode='lines+markers'))
    fig.update_layout(template='plotly_white',height=420,xaxis_title='Vade (gün)',yaxis_title='Yıllık oran (%)',legend=dict(orientation='h',y=1.2))
    st.plotly_chart(fig,use_container_width=True)
    st.download_button('Karşılaştırmayı CSV indir',frame.to_csv(index=False).encode('utf-8-sig'),'vade_karsilastirma.csv','text/csv')

with methodology_tab:
    st.markdown('''### Hesaplama notları

- **TL mevduatın efektif maliyeti:** `(mevduat faizi − ZK oranı × ZK neması) / (1 − ZK oranı)`.
- **TL mevduat eşleniği:** `alternatif yıllık oran × (1 − ZK oranı) + ZK oranı × ZK neması`.
- **Repo:** Faiz anapara × yıllık faiz × gün / baz; değişken bp ve sabit giderler işlemin yönüne göre eklenir/çıkarılır. Komisyonun tüm vadelerde bir kez alındığı varsayılır.
- **USD mevduat + swap:** USD fonlamanın ZK sonrası maliyeti, spot ve forward kuru ile TL maliyetine dönüştürülür. Swap gideri TL anaparaya bp olarak eklenir.
- **Kuponsuz DİBS:** İtfa/alış maliyeti üzerinden vadeye kadar basit ve bileşik getiri hesaplanır.
- **Kuponlu DİBS:** Nakit akışlarından efektif yıllık iç verim bulunur. Ayrıca kuponlar belirlenen faizle itfaya taşınarak dönem getirisi ve mevduat eşleniği hesaplanır.

**Sınırlamalar:** Tek dönemli ZK, sabit nema, vergi öncesi oran, eşleşen vade, karşı taraf/teminat/likidite etkilerinin hariç tutulması. Kur ve forward verileri canlı değildir. Bu araç kurumun fiyatlama ve risk politikalarının yerine geçmez.
''')
